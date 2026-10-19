# betangel-suite: design (MVP: offline replay and paper trading)

| | |
|---|---|
| Status | Draft 0.2, for review (review round 2 applied; see Appendix B). Yu's Phase 0 rulings recorded 2026-10-15, Yu's Q-Y8 answer 2026-10-16, and Yu's answers of 2026-10-17 (section 2.2.1). Nuance's PR #1 review applied 2026-10-16 and 2026-10-17 (Appendix C), and Nuance's PR #2 review (Appendix D). Round 5, 2026-10-17: Astra's PR #1 review, Nuance's PR #1 re-review and Nuance's answers of 2026-10-17 applied, and on this branch Astra's and Nuance's re-reviews of PR #2 (Appendix F). Round 5 close, 2026-10-19: Yu's words of 2026-10-18 as relayed by Nuance (section 2.2.1), Nuance's PRO ladder count, and Nuance's answers on release ancestry, the port check and the runbook's L1 layout check (Appendix F). Round 5 confirm, 2026-10-19: the relayed answers confirmed by Yu in Yu's own hand (section 2.2.1; Appendix F). Round 6, 2026-10-19: Astra's and Nuance's reviews of the round 5 heads, and on this branch the code findings of both reviews of PR #2; Yu's approval of this document's size exception (section 2.2.1); and lab-Claude's recheck (Appendix F). |
| Date | 2026-10-15 |
| Author | lab-Claude (Claude Code session 03026dfa on the lab MacBook Pro) |
| Reviewers | Nuance (Air Claude, owner of betangel-research), Astra (Codex reviewer) |
| Approver | Yu |
| Upstream pin | cambridgetcg/betangel-research `76f71dc94588a50f0df56dde2c3fabcf6e102f88` |
| Repository | cambridgetcg/betangel-suite (private), cloned at `~/betangel-suite` |

**How to read this document**

- **Citations.** A citation `file.py:N` refers to betangel-research at 76f71dc, in `betangel_research/betfair/` unless another path is given. I opened and checked every citation on 2026-10-15. Draft 0.2 re-checked every contested citation against a `git archive` snapshot of 76f71dc.
- **Labels on numbers and claims:**
  - *Measured (synthetic)*: measured on this M1 (8 GB) on 2026-10-15 by the three design drafts, on synthetic data only. A range means the drafts' synthetic markets had different ladder depths.
  - *Measured (real, aggregates)*: measured by a reviewer on 2026-10-15 on the PRO TAR in `incoming/`. The TAR was read in process and read-only with upstream 76f71dc code, at nice 10. Only aggregates were kept, nothing was written, and betangel-research's git status was clean afterwards.
  - *Estimate*: a planning guess.
  - *Inference*: reasoned through but not tested.
- **The oracle.** "The oracle" means betangel-research's batch paper replay, `paper.run_paper_replay`, together with its internal driver `_simulate`. The suite has to agree with it.

---

## 0. Summary

betangel-suite is Yu's personal macOS trading suite. Its first job is to be a **spoiler-free replay ladder and paper-trading trainer** for GB/IE WIN horse racing. It works over the free 2015-05..2016-04 PRO year and has no live path.

The loop:

1. Pick an unseen race.
2. Watch the full-depth ladder from T-10 min.
3. Trade on paper by click or key, and green up before the off.
4. Watch the race in-play (view only).
5. Read a debrief at Betfair Basic 2% commission.

Shape:

- **Engine.** One Python 3.13 process, standard library only, started through a fixed launcher (`python3.13 -I -S -B`). It runs with `BETANGEL_BETFAIR_FORBID_NETWORK=1` and has no credential code path.
- **UI.** A browser UI served on `127.0.0.1:8765`. A single-use bootstrap code in the URL is exchanged for a session token that is held in memory only. Later a native SwiftPM shell replaces the browser, before any live click (section 12, L1).
- **Viewing.** Yu can use the lab's own screen. From the Air, Yu uses a forced-command SSH tunnel key plus an sshd drop-in that Yu installs (R-2). This is offered from Phase 0. Viewing from the Air waits for the merged Phase 0 stack and Yu's release of it (section 8.6).
- **Upstream code.** betangel-research is reused from a read-only, network-free local clone pinned at 76f71dc. Every file is hash-checked, and imports go through one facade module. The engine imports 25 upstream modules (verified 2026-10-15). None of them is gateway, transport, auth, credentials, esa, api, recorder, killswitch, arming, presence, reconcile, risk or capability.
- **Book state.** `book.MarketBookCache` rebuilds the book. A small yield tracker mirrors `book.snapshots_from_recording`, so the suite can produce exactly the snapshot the oracle would see at any moment without taking a snapshot of every message.
- **Paper fills.** These come from `paper.PaperExchange`, driven directly rather than through the gateway, with a suite-owned `journal.OrderJournal(path, mode="paper", clock=<SimClock>)` per session.
  - While any paper order is pending or open, the suite steps the exchange on every message that changes the market, as the oracle does. If the CPU cannot keep up, the replay clock lags; it never skips messages.
  - Parity with the oracle is tested on synthetic fixtures under a stated contract (section 7.4).
- **Coexistence.** No engine runs during Nuance's announced runs or ingests. A marker file outside `~/betangel-data`, on Nuance's terms, stops it, and a lock Nuance's wrapper takes waits for real-data commands (section 6.8).
- **No policy amendment needed, except for the ladder type.** The MVP needs no amendment to trading policy and no change to betangel-research, except on one point. `book.py` reads the ladder type only from `priceLadderDefinition`, and without it V9 refuses every real paper click. Nuance's counts found that key in none of the 12,208 BASIC markets and none of the 12,208 PRO markets of the engineering year (section 7.1). So Phase 1b needs Nuance's U-10 and any V9 change Yu rules on under D-5.
  - It does need a one-page **Phase 0 packet** of rulings from Yu (R-1..R-7, section 2.2).
  - The packet includes the three points Nuance said need Yu's ruling before code (mailbox, 2026-10-15 12:30Z): driving `PaperExchange` directly (R-1), SP display (R-5), and rule-generated paper orders (R-6; the MVP has none).
- **Plan.** Phase 0 (scaffold and viewing), Phase 1a (replay ladder), Phase 1b (paper) and Phase 1c (polish and sign-off).
  - *Estimate:* about 8-11 weeks of lab work, plus review waits.
  - Each phase has a lab-done exit and a review-accepted exit.
  - Review latency, not coding, sets the elapsed time. (c2b3b3 and c2b3b4, which Nuance was finishing first, are merged; Nuance, PR #1 review.)
  - **The first milestone Yu can see** is a synthetic ladder in the browser. *Estimate:* target 2026-10-29.
  - The first real PRO race is its own milestone, dated once Nuance gives an ingest date.
- **Later.** The native shell (on the Air, reaching the lab engine over SSH stdio), Air-side work (owned by Nuance, in a repo never cloned on the lab), live stage-and-type, policy-gated live one-click, and automation research. These come later and each needs its own approval.

---

## 1. Purpose and non-goals

### 1.1 Purpose

1. **Replay.** Faithful, spoiler-free replay of licensed Betfair Historical Data PRO markets, with pause, speed and seek.
2. **Paper practice.** The core Bet Angel interactions: one-click ladder, one-click grid, cancel keys, close trade (green-up), What-If P&L and countdown. Fills come from betangel-research's own conservative paper-v1 model, at Basic 2% commission.
3. **Research companion.** Practice is recorded in hash-chained journals, so it is reproducible and auditable. A viewed-markets ledger lets Nuance and Astra account for human exposure to data, through counts-only summaries (section 5.5). Hooks are left for a later overlay of the backtester's vocabulary (decision time, cohort reasons).
4. **Foundation.** The suite is the base for later, separately approved live features.

### 1.2 Non-goals for the MVP

- **No live path of any kind.** No Betfair API, login, credentials, Keychain access, order gateway, delayed or live stream, or account data on the lab. There is no live endpoint in the code, not even a disabled one. Later live and Air code lives in a separate repo that is never cloned on the lab (section 3.1).
- **No automation.** No offsets, stops, trailing stops, auto-green, dutching or timed actions. AGENTS.md:9 allows simulated order intents from strategies only inside `betangel_research/betfair/backtest`. Every paper order on real data is an operator click. Scripted orders exist only in synthetic tests (R-6).
- **No edge.** The suite adds tools, not an edge. Nothing in betangel-research has passed an out-of-sample economic test. Paper results are labelled `paper_simulation_not_execution_evidence` (paper.py:62).
- **Out of scope:** in-play orders, PERSIST, BSP orders, PLACE and each-way markets, sports other than horse racing, and stakes under £1. `validate_place` refuses these in paper mode too:
  - in-play, non-WIN and non-horse-racing markets through V9 (validate.py:102-121);
  - PERSIST through V6 (validate.py:220-221);
  - BSP and other instruction shapes through V0, because the instruction keys must equal `INSTRUCTION_V1_KEYS` exactly (validate.py:190-192; schemas.py:32);
  - stakes under £1 through V5 (validate.py:212-219).
  
  GB/IE is a filter in the suite's catalogue, not a V-rule: the repo's rules hold only `market_types ["WIN"]` and `event_type_ids ["7"]` (config.py:63).
- **No changes elsewhere.** Nothing in betangel-research changes, and none of Yu's trading policies change, except what the ladder type needs: Nuance's U-10 and any V9 change Yu rules on under D-5 (section 7.1).

### 1.3 What "live" means today

Under current policy, a home-built suite's live part would be a **£2 typed bet slip**, not a ladder. The limits are:

- default caps (config.py:58-62): £2 stake, £10 liability, £20 market and £50 total exposure, £20 daily loss, 6 orders a minute, 1 instruction per request;
- horse-racing WIN with one winner on a CLASSIC ladder and never in-play (V9, validate.py:102-121), and in live mode within 30 minutes of the off (V9b, validate.py:122-130; `max_minutes_before_off`, config.py:62);
- one fresh CLI process per order, with its own login, and a line the operator retypes at `/dev/tty` (presence.py:1-11, :80).

Ladder trading, live greening and automation need explicit policy proposals (section 14). Whether the MVP practises live v1 or Bet Angel-style ladder trading is Yu's choice (R-7). Either way, a "live v1 shadow" badge shows wherever paper practice goes beyond what live v1 allows.

---

## 2. Decisions and constraints

### 2.1 Yu's decisions (recorded 2026-10-15)

| ID | Decision |
|---|---|
| D-1 | Build, not buy Bet Angel. "I personally prefer building, not in a rush for trading": the suite is first a replay, paper and research tool, and live comes later. |
| D-2 | UI is a localhost web UI over a Python engine that reuses betangel-research. A thin native macOS shell (SwiftPM WKWebView over a Unix socket) comes later, before any live click. |
| D-3 | Code lives in the new private repo cambridgetcg/betangel-suite (`~/betangel-suite`, empty today, remote over HTTPS). It depends on betangel-research at a pinned commit and never edits it. |
| D-4 | Roles. Lab-Claude builds the offline replay and paper MVP on the lab. Nuance and Astra review. Nuance owns every betangel-research change and policy amendment, and Air-side and live work later. |
| D-5 | Trading policies are open to change for the suite: AGENTS.md, D1-D5, the typed `/dev/tty` gate, caps and worst-case risk accounting. A change is made only by an explicit proposal, reviewed by Nuance and Astra and approved by Yu. |
| D-6 | Commission: Betfair Basic package, 2% (Yu: "Basic 2%"). Whether the label is verified or unverified is R-3. |
| D-7 | Data: the free horse-racing year 2015-05..2016-04 at PRO tier, downloaded by Yu. Nuance ingests and indexes it. |
| D-8 | The £499 live key will be bought when it is needed (Yu: "buying the £499 key whenever needed, I am commited to it anyways"). The MVP does not need it. |
| D-9 | The Air's chip is M2. This matters for the later native shell, which runs on the Air (L1), and for any Parallels use. |

*Lab-Claude's note on D-5, not part of Yu's decision:* the MVP needs no policy change, except possibly for the ladder type. Nuance's counts found no `priceLadderDefinition` in the BASIC or the PRO engineering-year markets, so Phase 1b needs Nuance's U-10 and any V9 change Yu rules on under D-5 (section 7.1).

### 2.2 Rulings for Yu: the Phase 0 packet

All seven rulings go to Yu together on one page in Phase 0, alongside Q-Y8 (who merges). Each one is needed only before the code that depends on it.

Points R-1, R-5 and R-6 are the three Nuance listed as needing Yu's ruling before any suite code (mailbox, 2026-10-15 12:30Z, item 4). The design's answer to each is given below.

| ID | Question | Needed before | Recommendation |
|---|---|---|---|
| R-1 | May the suite drive `paper.PaperExchange` directly, with its own paper journal, outside `gateway.py`, for paper orders Yu clicks on historical replay? The order-path document makes `gateway.py` the single choke point (docs/betfair-order-path.md:12). betangel-research's own `run_paper_replay` already drives `PaperExchange` outside the gateway (paper.py:827-937). | Phase 1b code | **Yes.** The deciding reasons are the gateway's import closure and RiskGuard:<br>- the gateway imports the credential, arming, killswitch, presence, reconcile and risk modules (gateway.py:65-89);<br>- it uses RiskGuard, and `risk` and `capability` are INTERNAL_ONLY (tests/test_betfair_boundaries.py:22).<br>The per-Mac `.paper.lock` (gateway.py:612; paths.py:81-82) would clash with Nuance's CLI paper commands only at the default state root. Under `StatePaths(root_override=...)` with FORBID_NETWORK (paths.py:62-69), the lock would sit under the suite's own root. |
| R-2 | Viewing from the Air: a forced-command tunnel key, plus an admin sshd drop-in that closes reverse and Unix-socket forwarding (section 8.6). Yu generates the key and runs the staged lab script with sudo; nobody else runs it. | Phase 0 (Yu's first look from the Air) | Yes. |
| R-3 | The commission label for Yu's "Basic 2%". Either `user_package_verified` on Yu's word (docs/betfair-integration.md:229 says to use it once you know your package), or `user_package_unverified` until Yu checks My Account. `official_example_basic_2pct` also exists (constants.py:185). | Phase 1b | Yu picks one in the packet. Until Yu answers, the default is `user_package_unverified`. |
| R-4 | The suite state root `~/betangel-data/suite.noindex`. The `.noindex` suffix keeps Spotlight out of it. Yu and Nuance decide. | Phase 0 | Agree (section 3.7). |
| R-5 | SP display. Instead of a `schemas.py` change, a suite-side, display-only parser reads the SP fields from the stream dicts. Its values are never passed to `validate` or `PaperExchange`. Separately, non-finite `spb`/`spl` content can invalidate a book inside `book.py` today (section 2.4). | Phase 1a (SP display) | Yes. Nuance to confirm that no repo ruling is needed (Q-N9). |
| R-6 | Rule-generated paper orders outside `betfair/backtest` (AGENTS.md:9). | Phase 1b | **None in the MVP.**<br>- Every order on real data is an `OperatorClick` minted from an HTTP request.<br>- Scripted orders (`TestOrder`) exist only in synthetic mode, which refuses every real data root (section 7.1).<br>- Yu confirms this.<br>A real-data scripted smoke test, or `diagnose` re-executing a session's clicks on real data, would need a separate yes here. |
| R-7 | The learning target:<br>- **"practise live v1"**: today's defaults, which are the `v1-live-mirror` caps (a £2 stake), live-parity mode, and no replace or drag;<br>- **"learn Bet Angel ladder trading"**: the `practice` profile by default, with paper replace, drag-to-move and size reduction in exploration mode from Phase 1b.<br>The live v1 shadow badges stay in both. | Phase 1b | Yu's call. Both are built. Until Yu answers, the default is live v1. |

The packet also asks Nuance's Phase 0 questions (section 15.2): Q-N1..Q-N5 and Q-N12.

#### 2.2.1 Yu's answers (2026-10-15 to 2026-10-17)

Yu, in the lab session: "bet angel never used. Lets go with what you recommended for all."

| ID | Ruling |
|---|---|
| R-1 | **Yes.** The suite drives `paper.PaperExchange` directly with its own paper journal, outside `gateway.py`, for paper orders Yu clicks on historical replay. |
| R-2 | **Yes.** Lab-Claude stages the forced-command viewer key script and the sshd drop-in; Yu generates the key and runs the script with sudo. |
| R-3 | **`user_package_verified`, on Yu's words of 2026-10-18 as relayed by Nuance: "confirm account is basic 2%"** (below; Q-Y3), confirmed by Yu in Yu's own hand on 2026-10-19. Until the relayed answer, R-3 was a stated default (the packet made no recommendation): `user_package_unverified` until Yu checks the package in My Account, which lab-Claude read "Lets go with what you recommended for all" as leaving in place (lab-Claude's reading, not Yu's words). The config default follows only through a reviewed change, before Phase 1b (section 3.8). |
| R-4 | **Agreed by Yu.** `~/betangel-data/suite.noindex`. Nuance agreed it on three conditions in Nuance's PR #4 review, and `roots.STATE_ROOT_AGREED` was then set True (section 3.7). Nuance's PR #2 review makes that agreement conditional again, on Nuance's PR #2 item 1 (Q-N3). That item is fixed on this branch (62c39c6, 851885a). Nuance's PR #2 re-review agrees it again as built at 823c194, pending that re-review's findings F4 and F5, on conditions (section 3.7). F4 and F5 are fixed on this branch (ff35218, c3b0c61). Nuance's review of PR #5 at 52a9edc agrees both halves of Q-N3, the root and the marker, as built at that SHA, on conditions (section 3.7); Nuance confirms it at the merge SHA in one line. |
| R-5 | **Yes.** A suite-side, display-only SP parser; no `schemas.py` change. Nuance confirmed it on the terms in section 6.6 (Q-N9, PR #1 review, 2026-10-16). |
| R-6 | **Confirmed.** No rule-generated paper orders in the MVP. Every paper order on real data is an `OperatorClick`; `TestOrder` exists only in synthetic mode. |
| R-7 | **Stated default (the packet made no recommendation; Yu has not picked): practise live v1** (`v1-live-mirror` caps, live-parity mode). The packet left the choice to Yu. Lab-Claude reads "Lets go with what you recommended for all" as leaving this default in place (lab-Claude's reading, not Yu's words). The choice stays open, and the `practice` profile is still built and selectable. |

**Q-Y8, who merges: not one of the 2026-10-15 answers.** An earlier version of this table listed a Q-Y8 row here: lab-Claude merges after the routed reviewer accepts, UI-only PRs merge on Yu's acceptance alone, and "Yu can veto or revert any merge". That row is withdrawn. Nuance found no source for its merge half or for "Yu can veto or revert any merge" (PR #1 review, item 10). Nuance pointed to section 3.9's recommendation (UI-only PRs need only Yu's acceptance) as the source of the UI-only half.

- **The packet's line:** "Who merges pull requests (Q-Y8): you, or me after Nuance or Astra has reviewed? And may UI-only changes go in on your approval alone?" It gave no recommendation, so "Lets go with what you recommended for all" did not answer it.
- **Yu's answer** (2026-10-16, in the lab session): "Its all good :) Merge when sensible".
- **Lab-Claude's reading of "sensible"** (lab-Claude's, not Yu's words; Yu can override it):
  - lab-Claude merges a PR only when every reviewer routed to it in section 3.9 has accepted the same head SHA, and the tests pass on 3.13 and 3.11 at that SHA;
  - under the governance row Yu adopted on 2026-10-17 (below; section 3.9), a PR that touches a rule document waits for both Nuance and Astra to accept the same head SHA; a change of meaning in a rule document also waits for Yu (rule 10) unless both Nuance and Astra say it does not widen; a PR that changes AGENTS.md's rules or routing also waits for Yu's approval of those AGENTS.md changes; and a PR whose diff includes a file that no row covers waits for Yu's acceptance (the fail-closed row in AGENTS.md now sends such files to Yu; below). A UI-only PR, as narrowed later that day, merges on Yu's acceptance alone (Yu's answers of 2026-10-17, below);
  - Nuance's condition on the flag (Nuance's answer to lab-Claude's question 8 of 2026-10-17, PR #2 re-review): "no merge with the flag True unless my agreement is recorded at the merge-candidate SHA". The flag is `roots.STATE_ROOT_AGREED`, True on the unmerged branches (section 3.7), so the sitting also waits for Nuance's agreement of the state root and the marker, recorded at the SHA that merges. Nuance agreed both halves as built at 52a9edc, on conditions, and confirms the agreement at the merge SHA in one line (Nuance's review of PR #5 at 52a9edc; section 3.7);
  - PR #5 also waits for Yu's written approval of proposal 002 (on phase0/viewing), after Nuance's and Astra's reviews of it;
  - #2, #4 and #5 each change AGENTS.md's rules or routing, so each also waits for Yu's approval of its AGENTS.md changes, in addition to its reviewers;
  - the merge order is lab-Claude's decision: #1, #2, #4 and #5 merge in one sitting, in that order, with nothing merged in between, each accepted at its head SHA, after Yu's written approval of proposal 002, and Yu's approval of the AGENTS.md changes in #2, #4 and #5. That is the option Nuance offered, "merge the four together". Some fixes exist only on a later branch and correct text that an earlier PR still carries (f931637, ab766a0 and 0c1335b, on #5; Nuance's PR #1 review, P3: "merge the four together, or move each fix down"). Stale text that can stand on its own is also moved down to the earliest branch that carries it, as 3.2's fork-and-spawn sentence and the `risk` oracle rows (sections 4.2 and 7.7) were moved to #1.
- **The UI-only half: answered by Yu on 2026-10-17 ("Lets go with what you recommended for all :)"): yes.** UI-only PRs merge on Yu's acceptance alone, and section 3.9's UI-only rule is binding (section 3.9 defines UI-only). Until then lab-Claude had treated it as open, although Nuance points to section 3.9 as its source: the packet, the page Yu answered on 2026-10-15, put it to Yu with no recommendation, and Yu's 2026-10-16 answer does not take it up separately. Lab-Claude's message of 2026-10-17 put it again, recommending yes, with section 3.9's definition (below). Narrowing that definition was put to Yu later on 2026-10-17, and Yu answered yes that day (below; section 3.9).

**Bet Angel on Yu's Betfair account:** never used (Yu, 2026-10-15), so the design needs no handling for orders or limits shared with Bet Angel. If Bet Angel is ever installed against the account, that needs a fresh review first.

**Yu's answers of 2026-10-17.** Yu, in the lab session, replying to lab-Claude's message of 2026-10-17, which put each question below with lab-Claude's recommendation: "Lets go with what you recommended for all :)". It answers only the questions that carried a recommendation. That Yu's words answer exactly these, each as its recommendation stood, is lab-Claude's reading, not Yu's words. Lab-Claude's message recommended each; for the governance row, Q-Y9 as reworded and the Air's CLAUDE.md line, its recommendation was to adopt Nuance's (Nuance's PR #1 review, items 9, 2 and 6). The 2026-10-15 words above, nearly the same, did not cover Q-Y8, which had no recommendation then.

- **The governance row for rule documents (Q-Y8, Q-N12): adopted, as Nuance recommended** (Nuance's PR #1 review, item 9). Rule documents (AGENTS.md, this document, `docs/data-handling.md`, `docs/proposals/`, `tools/stage/`) go to Nuance and Astra, accepted at a named head SHA; a diff that no row covers goes to Yu; and a change of meaning follows rule 10 (Yu) unless both reviewers say it does not widen. Also adopted: Nuance's PR #2 addition, "changes to AGENTS.md's rules or routing also need Yu". Section 3.9 makes these binding.
- **The UI-only half of Q-Y8: yes.** UI-only PRs merge on Yu's acceptance alone. Section 3.9 defines UI-only; a PR that also touches a rule document is not UI-only. Yu narrowed the definition later that day (below).
- **Q-Y9, as reworded: confirmed.** Agents never read real values; Yu describes the shape, or a code-only `diagnose` check runs. Real fields reach a model provider only with Betfair's specific written agreement naming that provider, plus Yu's OK each time, scoped to one problem report and named fields. Until such an agreement exists, exceptions are not available (rule 5; section 8.7).
- **The screen-capture line in the Air's CLAUDE.md (Q-Y10; Nuance's PR #1 review, item 6): approved, and now in.** Nuance added it on the Air, in Nuance's own config, and confirmed on 2026-10-17 (08:48Z) that it is in the "Betangel suite" section of the Air's `~/.claude/CLAUDE.md`; Nuance reports that Yu confirmed it to Nuance directly (Nuance's PR #1 re-review, finding 4). It is a CLAUDE.md rule for Claude Code sessions on the Air; for Astra and other tools it is conduct only (section 8.6).
- **Q-Y11: yes, a Safari Private window for the suite on both machines.** The lab Safari clean-up now (sign out of historicdata.betfair.com, and delete saved betfair.com passwords and betfair.com site data): agreed by Yu on 2026-10-17, for Yu to do by hand. Since 2026-10-18 it is recorded as done, on Yu's words as relayed by Nuance (below). Agents never touch browser data or passwords (section 8.6).
- **The optional `~/.ignore` (Q-Y9): not added**, as lab-Claude recommended. It would not have helped: it hides a folder only from ripgrep, not from Claude Code's shell `grep` or from `find` (Nuance's PR #2 re-review, F12).

What follows from these:

- **The fail-closed row is superseded.** The row that lab-Claude added to AGENTS.md on this branch (67524f4; labelled as lab-Claude's reading in 818fb17) sent files that no row names to Astra and Nuance jointly. That was lab-Claude's reading of the "fail-closed row for unnamed files" in Nuance's PR #2 review, which names no reviewer, and it was asked of Nuance on 2026-10-17. Under Nuance's own item 9 text, which Yu adopted, files that no row names now go to Yu, so that question to Nuance is moot. Nuance has since withdrawn that row, which "named no reviewer, so disagreed with item 9; my slip" (Nuance's answer to lab-Claude's question 1 of 2026-10-17, PR #2 re-review). AGENTS.md's fail-closed row now says so (section 3.9; Appendix E).
- **AGENTS.md changes need Yu.** A PR that changes AGENTS.md's rules or routing needs Yu's approval of those AGENTS.md changes before it merges, in addition to its reviewers. #2, #4 and #5 all do.

**Yu's later answers of 2026-10-17.** Lab-Claude put two more questions to Yu that day, each with lab-Claude's recommendation, and Yu answered both in the lab session, after lab-Claude's messages that day. Yu's words are quoted exactly; the recommendations are described in lab-Claude's words, and that Yu's words adopt each one as it is set out here is lab-Claude's reading. Section 3.9 makes both rows binding.

- **Test files: "yes lets go with what you recommended"** (Yu, 2026-10-17). Lab-Claude had first proposed a row that sends each test file to the reviewers of the code it tests, so that ordinary test changes do not all go to Yu. Nuance then recommended it only in a mechanical form, "a test → the reviewers of the modules it imports, else Yu", and called the row "Yu's to decide" (answer to lab-Claude's question 1). Lab-Claude recommended that form to Yu: a test file goes to the reviewers of the modules it imports, and a test that imports no routed module goes to Yu.
- **Narrowing UI-only: "ohh understood. Yes lets go with what you recommended"** (Yu, 2026-10-17, after lab-Claude explained the narrowing). Nuance's PR #1 re-review (finding 3) found that the rule against automation lives only in `ui/` JavaScript, which a UI-only PR could change with only Yu's review. Lab-Claude recommended Nuance's fix: UI-only excludes the code that sends commands (command call sites and the sender in `ui/stream.js`), the keyboard shortcuts that trigger orders (command keymap entries), the access-token handling, and timer paths that lead to the sender; changes to those go to Astra, and to Nuance as well for paper-trading keys; `tests/test_ui_assets.py` goes to Astra; and everything else in `ui/` that only changes how pages look goes in on Yu's approval alone. Lab-Claude's explanation cited Nuance's finding that holding the space bar repeats play (on phase0/viewing at fcbf7cd, `keyAction` returns `toggle_play` for a repeated space).

These answers cover nothing else. Still open after them, among others: R-7 (a stated default; Yu has not picked), Q-Y5..Q-Y7, Q-Y12..Q-Y15, and the questions of round 5 to Nuance and Astra that are not yet answered (Appendix F). Q-Y3/R-3 has Yu's answer as relayed by Nuance, confirmed by Yu in Yu's own hand on 2026-10-19 (below). Nuance answered lab-Claude's nine questions of 2026-10-17 in the PR #2 re-review (Appendix F). Proposal 002 still needs Yu's written approval, after Nuance's and Astra's reviews of it.

**Yu's words of 2026-10-18, as relayed by Nuance.** Yu answered several questions in chat with Nuance on 2026-10-18, and Nuance relayed Yu's words to lab-Claude that day (Nuance's mailbox note of 2026-10-18, 22:37Z). They are recorded here as Yu's words as relayed by Nuance, quoted exactly as Nuance quotes them; each reading is Nuance's unless marked lab-Claude's. A relay is context, not Yu's instruction or acceptance (section 3.9). The relayed answers were confirmed by Yu in Yu's own hand on 2026-10-19, when Yu wrote to lab-Claude: "yes confirm all on Nuance's relay". Those words cover Q-Y3 (R-3), Q-Y11, Q-Y17 and Q-Y18 (lab-Claude's reading). That confirmation is why they now count as Yu's answers; the quotes stay labelled as Yu's words of 2026-10-18 as relayed by Nuance, because that is where the words came from.

- **Q-Y3 (R-3), the commission label: "confirm account is basic 2%".** Nuance's reading, which lab-Claude records: `user_package_verified`. R-3 is picked (the table above; sections 3.8 and 15.1).
- **Q-Y11, the lab clean-up: "Pw deleted too".** Nuance's reading: Yu did the clean-up on the lab, and nothing is left for an agent to do. The clean-up is recorded as done (sections 8.6 and 15.1).
- **Q-Y17 and Q-Y18** (STOP from a read-only tab, and who makes release copies) are asked only on phase0/viewing, from the Phase 0c build, so Yu's relayed answers to them are recorded there.
- **Two answers repeat Yu's of 2026-10-17** and are consistent with them, so nothing changes here: on UI-only, "yes UI-only accept 咗就 merge 得" (Nuance's reading: "A UI-only PR may merge on Yu's acceptance alone."), and on the governance row, "改 AGENTS.md 嘅規則或者 routing要批" (Nuance's reading: "Changes to AGENTS.md's rules or routing need Yu's approval.").

**Yu's answer of 2026-10-19 on the trainer.** Proposal 003 (the agentic-first re-scope, on its own branch and not merged) proposes, as its RS-1a, cancelling the manual trainer; its cuts include 1a's UI, 1b's operator paths, all of 1c and the later L1 native shell. Yu, in the lab session on 2026-10-19: "confirm trainer drop and also manual live order tools". Two questions put in round 5 are about trainer operator paths only, so they are recorded as moot rather than answered (lab-Claude's decision): whether the system-stop proposal widens I-8 (section 7.1), and lab-Claude's reading of the cancel timing of section 7.6. Nuance proposed it: "Q1 (SystemStop and I-8) and the 7.6 cancel timing are about trainer operator paths that RS-1a cancels. I propose we record them as moot rather than review them." (Nuance's mailbox note of 2026-10-19, 11:08Z). Astra's and Nuance's reviews of PR #1 at af960fd agree that both are trainer-only and moot. Both stay labelled proposals, and recording them as moot adopts neither. What the agent loop keeps needs its own reviewed contract, owed in proposal 003: in Astra's words, "Agent-loop halt/recovery and pending-order cancellation precedence still need explicit semantics" (Astra's review of PR #2 at 4fa5835); in Nuance's, "Any stop path the agent loop keeps needs its own reviewed contract in proposal 003" (Nuance's review of PR #1 at af960fd). RS-1a's other cuts are not applied in this document; they follow proposal 003's own review.

**Yu's answer of 2026-10-19 on this document's size.** Astra's and Nuance's reviews of PR #1 at af960fd (Astra's item 1, Nuance's F1) found that the scanner's size exception for this document widens section 5.6's rule, so it was put to Yu. Yu, in the lab session on 2026-10-19 (about 13:30Z), answering lab-Claude's question "Confirm: the design doc may grow past 512 KB, up to 2 MB, still scanned and reviewed; every other file stays under 512 KB?": "Yes, approved". That answer is in Yu's own hand. Earlier that day (about 13:10Z) Nuance had relayed Yu's words from Yu's chat with Nuance: "design.md increase批准 :)". The relay is recorded as Yu's words as relayed by Nuance; as with any relay, it was context, and Yu's own words above are the answer (section 3.9). So the exception for this document is approved by Yu: up to 2 MiB, still content-scanned, and every change to it reviewed by Nuance and Astra; every other file stays under 512 KiB (section 5.6).

**Asked of Yu on 2026-10-19, not answered yet:** setting the GitHub repository to allow merge commits only (section 3.9). Yu's words go here when they come.

### 2.3 Hard constraints (lab rules and agreements)

- **No Betfair credentials on the lab.** Nothing runs that logs in or touches the network or an account. The engine refuses to start without `BETANGEL_BETFAIR_FORBID_NETWORK=1`.
- **Licensed data.** It is for Yu's personal internal use only. It is never committed, uploaded or shared. Data and its derivatives stay under `~/betangel-data`, outside every git clone. No 2026 month ever reaches the lab. Tests use synthetic fixtures only.
- **No changes to betangel-research.** The lab clone `~/betangel-research` is fast-forwarded by the Air's script at any time, so the suite never imports from it and never writes into it. That includes `.git/index`, which `git status` can refresh (section 4.2).
- **Python.** `/opt/homebrew/bin/python3` (3.15.0) is frozen for Nuance's certification. It is not used and nothing replaces it. python3.13 (3.13.16) and python3.11 (3.11.17) are available. Node 24 is at `~/.local/bin/node`. There is no Xcode (Command Line Tools only, Swift 6.3.3) and no Apple ID.
- **Nuance's runs.**
  - No suite engine runs during Nuance's announced real backtest runs or PRO ingest. Nuance asked: "A suite elsewhere is harmless but slows the run; please avoid it" (mailbox 08:57Z, A5).
  - No changes under `~/betangel-data`, and no heavy load.
  - Do not use `~/betangel-data/lab-state` (Nuance's, agreed upstream: the runbook at 4d7bcd3, line 507, per Nuance's PR #1 review) or `~/betangel-data/logs` (it exists and is not ours).
- **Ask Yu first** for anything that needs the admin password, installs system software, or changes security settings. That includes the sshd drop-in, the viewer key, Spotlight Privacy, Analytics sharing and Screen Recording. Never ask Yu to paste a secret.
- **Betfair key terms (later phases L2-L4).**
  - The delayed key must be used for simulation and practice applications (Application Keys DD/2687105).
  - Read-only use of the live key is not permitted and can get the £499 key deactivated (SA/25033076334748).
  - Hence: paper or practice never runs on live-key data; live-key market data is shown only in sessions that place real bets; and DELAYED stays the only paper source on the Air.

### 2.4 Facts this design relies on (checked 2026-10-15)

- **betangel-research.** HEAD is `76f71dc` and the working tree is clean.
- **Index counts.** The lab's BASIC index has 52,561 records, of which 12,200 are GB/IE WIN markets in the engineering year. 49.5% of those have a REMOVED runner, and 46.4% had one before the decision cutoff. These counts were taken by the review judges; counts only.
- **The PRO year has landed.**
  - `~/betangel-data/historic/incoming/data.tar` (9,718,610,432 bytes) arrived on 2026-10-15.
  - It holds 12,208 `.bz2` members, all PRO and all at depth 6 (`PRO/YYYY/Mon/D/<eventId>/<marketId>.bz2`): market files only.
  - By path month: 12,200 fall in 2015-05..2016-04, the same count as the BASIC index's 12,200 engineering-year WIN markets, and 8 fall in 2016-May. That is a match of counts, not of markets (Nuance, Q-N4). These figures come from a header listing of sizes and path components only.
  - Nuance ingests it into a separate data root, `~/betangel-data/historic-pro`, so that P0's BASIC input descriptor stays unchanged (Q-N4). Nuance asked that `data.tar` and `incoming/` be left as they are.
  - **Ingested and indexed on 2026-10-19** (Nuance's job `pro-ingest-01`, under the run marker, with the stock `archive-ingest`, `archive-index` and `archive-audit` at research main 0d32421; Nuance's mailbox notes of 2026-10-18 and 2026-10-19, counts only): 12,208 members written to `~/betangel-data/historic-pro`, 0 refused, none in the sealed holdout and no 2026 month; P0's BASIC root was not touched. The index holds 12,208 markets: 12,114 indexed and 94 unreadable, all `malformed_runner`, the same count as the known BASIC 2015-16 quirk (a REMOVED runner listed twice); Nuance has not checked that they are the same 94 files.
  - **The suite reads only an indexed root, never `incoming/`.** A reviewer read the TAR read-only for the aggregates in section 6.7.
- **Free 2017 PRO samples.** These are not on the lab.
- **SP fields.**
  - `schemas.RUNNER_KEYS` has no SP fields (schemas.py:23).
  - `book.py` applies `spb`/`spl` as price points (`_PRICE_FIELDS`, book.py:56) and never puts their values in a snapshot. It ignores `spn`/`spf` entirely (book.py:266-294).
  - **They are not inert, though.** A `None` size in `spb` or `spl` comes from a `"NaN"` or `"Infinity"` string or a non-finite number (book.py:96-99, :355-362). It marks the whole snapshot `invalid_reason` `non_finite_size` (book.py:486-489, :460).
  - A non-finite `spb`/`spl` price poisons the runner (book.py:312-317).
  - Either way V9 refuses (`book_invalid`, validate.py:110-111) and paper cannot fill until the next image. PRO `SP_TRADED` content can therefore change paper behaviour, not just the display.
- **`-I` implies `-P` on python3.13.** `python3.13 -I -m pkg` does not find a package in the current directory. `python3.13 -I -S -B -m unittest discover -s tests -t .` works on 3.13 and 3.11 (tested in the scratchpad).
- **The GIL.** Homebrew's python3.13 has the GIL (`sys._is_gil_enabled()` is True on 3.13.16).
- **SSH.**
  - The lab's sshd leaves `AllowTcpForwarding` at its default of yes (`/etc/ssh/sshd_config:95` is commented out). No `AllowStreamLocalForwarding` is set, and `ClientAliveInterval` is at its default of 0 (`:106`).
  - TCP keepalive first probes after 7,200 s idle.
  - OpenSSH is 10.2p1.
  - The Air's existing key carries `from=`, `no-port-forwarding`, `no-agent-forwarding` and `no-X11-forwarding`, but no `command=`, so it is a full shell.
- **Display.** The lab's lid is open and its built-in display is online, with sleep and display sleep set to 0. Safari is the only browser in `/Applications`, and Yu has used it there for data downloads.
- **Swift.** CLT-only `swiftc` builds a WKWebView program (MacOSX26.5.sdk contains WebKit.framework). An offscreen WKWebView rendered a canvas and received a chunked NDJSON stream from a stdlib server with no permission prompt (section 11, uisnap).
- **Disk.** 151 GiB free on the lab disk.

---

## 3. Architecture

### 3.1 Components and processes

```
 lab MacBook Pro (M1, 8 GB, offline)                         MacBook Air (M2, Yu)
 +------------------------------------------------+          +------------------------------+
 | bin/suite --exec--> python3.13 -I -S -B         |          | Safari Private window:        |
 |  ONE engine process (flock'd single instance)   |  ssh -L  |   http://127.0.0.1:8765       |
 |   - actor thread: all mutable state             |<---------| ssh lab-suite (forced cmd)    |
 |   - loader thread: prescan, catalogue build     | Yu-      +------------------------------+
 |   - HTTP threads: 127.0.0.1:8765 only           | approved key + sshd drop-in (R-2)
 |   - control socket: run/control.sock (0600)     |
 |       ^ NDJSON stream, POST JSON                |
 | Safari (Private window) on the lab's screen     |
 | reads (read-only): indexed data roots only      |
 |   (~/betangel-data/historic-pro)                |
 | writes: ~/betangel-data/suite.noindex (0700)    |
 |         ~/.local/state/betangel-suite (0700)    |
 | imports: ~/.local/share/betangel-suite/deps/    |
 |          betangel-research-76f71dc94588 (ro)    |
 | runs Yu's commands from the release copy:       |
 |   ~/.local/share/betangel-suite/app/current     |
 +------------------------------------------------+
```

1. **Engine.** One process, started only through `bin/suite` (section 3.6). Standard library only. It runs under `os.nice(10)` and `umask 077`.
   - Every command Yu runs (`open`, `ssh-session`, practice) runs the reviewed release copy (section 8.6).
   - An engine started from a working checkout runs in **synthetic mode** only.
2. **UI.** Static HTML, CSS and ES-module JS served by the engine from an allowlist. No framework, build step, npm, CDN or external request. The ladder is drawn on a canvas; the grid and panels are DOM. `document.title` is always the static `betangel-suite`, never a race or venue.
3. **Control socket.** A 0600 Unix socket in the 0700 run dir. It lets a later `open`, `ssh-session` or `stop` attach to the running engine: to take over a stale session, to get a fresh bootstrap code, or to pause.
4. **Later (not MVP):**
   - **The native shell.** A SwiftPM WKWebView shell that runs on the Air (L1). It reaches the lab engine through the forced command `suite ssh-session --stdio`, which bridges the SSH channel to the engine's Unix socket with no port forwarding.
   - **Air and live code.** This lives in a separate repo under Yu's account, never in betangel-research, which is cloned on the lab (Nuance, Q-N13). That repo is **never cloned on the lab**. It uses its own entrypoint package, which the lab's AST and import tests forbid. `guard.py` has no off-switch: no environment variable or config flag disables it, so no code path in this repo turns the network on. The hook polices the calls it sees; it is not a sandbox against deliberate code in the same process (section 10, "The guard's scope").

### 3.2 Threads

- **Actor thread.** Owns all mutable state: the catalogue handle, the open market replay, clock, yield tracker, traded high-water tracker, checkpoints, paper desk, journal and folder. Every command arrives on one `queue.Queue`, so book and paper state need no locks. It ticks every 20-50 ms of wall time.
- **Loader thread.** Builds the catalogue and prescans the market being opened.
  - It prefetches the next race at the same meeting **only in display mode or while paused**. It works in chunks of about 2,000 lines, yields between chunks, and stops when an actor tick overruns.
  - The reason: python3.13 has the GIL. Prescan is pure-Python parse and apply (about 0.75 s of CPU for a median member and about 6 s for the largest), so running it during exact mode adds lag and jitter.
  - A worker process is not an option: the engine never starts one, as a rule. After `seal()` the guard refuses the audited and wrapped ways to start one (section 10, "The guard's scope"; Astra's PR #1 review, item 3, found the old "every way" too strong). In every phase it also refuses a direct `_posixsubprocess.fork_exec`, and importing `multiprocessing` or `concurrent.futures.process`: these start children with no audit event of their own (I-5; Nuance's PR #2 review, item 3, found the old "refuses fork and spawn after `seal()`" false for them; 56a2631). Since round 5 it also refuses a fresh load of `_posixsubprocess`, which would carry the unwrapped original, and the modules that run code in a subinterpreter, whose audit hooks are their own (Astra's re-review of PR #2, finding 1; Nuance's PR #2 re-review, F4; ff35218).
- **HTTP threads.** `ThreadingHTTPServer` with daemon threads. They only enqueue commands and read immutable frame objects, which the actor publishes by swapping a reference. There is one streaming GET per connected tab.

### 3.3 Data flow

1. **Catalogue.** For each configured data root (read-only):
   - read `index/<archive_sha>/head-v1.json` and check `markets_sha256` against `markets-v1.jsonl`;
   - check that `market_index.load_manifest` (market_index.py:225) returns the head's `manifest_sha256`;
   - stream `markets-v1.jsonl` and keep only the spoiler-free fields (section 5.3) in `<suite root>/catalogue/<index_head_sha256>.sqlite`.
   
   The catalogue is built only on an explicit `bin/suite catalogue` command, never automatically.
2. **Open a market:**
   - resolve the member with `archive.safe_target` (archive.py:662);
   - refuse a `None` month as `month_unknown`, then check the path month and `market_month(marketTime)` with `archive.month_gate` (archive.py:209);
   - read the compressed bytes into memory once, hash them, and compare with the manifest's sha256 and size;
   - decompress from those same bytes within stricter limits, and compare the decompressed size with the manifest's `decompressed_bytes`;
   - index line offsets and pts. Nothing decompressed is written to disk.
3. **Prescan.** Parse each line with `market_index.loads_strict` (market_index.py:215) and apply it to `MarketBookCache` (book.py:168). Advance the yield tracker, the SP and definition tap, and the traded high-water tracker. Take checkpoints on the section 6.4 schedule.
4. **Replay.** The clock applies whole pt batches up to the replay time. Frames are taken from lazily materialised snapshots at 10 Hz or less (configurable 5-20 Hz). While paper orders are pending or open, every yield of the market drives the paper exchange (exact mode, section 6.3).
5. **Commands.** UI POST → actor → `validate.validate_place` → journal intent and submit → at activation `PaperExchange.place` → `lifecycle.classify_place_report` → journal report → incremental `JournalFolder` → the next frame.

### 3.4 Repository layout (cambridgetcg/betangel-suite)

```
README.md
AGENTS.md                     suite rules (section 3.9)
pin/betangel-research.json    {repo, commit (full sha), files: {relpath: sha256}, python_floor}
bin/suite                     POSIX sh launcher (section 3.6)
bin/_launch.py                path setup, run-marker check, guard arming, dispatch
betangel_suite/
  __init__.py
  guard.py                    audit hook (startup phase, then sealed), environment refusals; stdlib only; no off-switch
  pin.py                      deps checkout lookup, per-file hash check, origin assertion, closure finder (deps never on sys.path), read_pinned
  rx.py                       THE ONLY module that imports betangel_research (section 4); maps upstream errors to codes
  roots.py                    state roots, the single writer helper (O_EXCL|O_NOFOLLOW, 0600/0700)
  release.py                  RELEASE.json check (release copy or synthetic mode)
  runmarker.py                the run marker and the real-data lock (section 6.8)
  errors.py                   closed error-code enum, salted identifier hashes, excepthooks
  config.py                   suite config, cap profiles, repo validate_config call
  data/      discover.py catalogue.py member.py reader.py roles.py ledger.py
  replay/    clock.py tracker.py checkpoints.py tap.py hwm.py frames.py budget.py
  paper/     desk.py click.py pending.py exposure.py greening.py rule4.py queuetrack.py session.py report.py
  api/       server.py auth.py routes.py stream.py static.py control.py
  cli.py     serve | open | ssh-session | stop | catalogue | selfcheck | diagnose | ledger-summary | release | test | uisnap | vendor
ui/          index.html app.js ladder.js grid.js keys.js chart.js style.css manifest.json sounds/
ui/tests/    *.test.mjs (node --test, no npm)
tests/       test_*.py (unittest); fixtures/gen.py (synthetic only, generated into temp dirs)
tools/       vendor_research.py hygiene_scan.py pre-commit commit-msg pre-merge-commit pre-push uisnap/ (Swift, section 11) stage/ (scripts staged for Yu)
docs/        DESIGN.md threat-model.md keymap.md data-handling.md proposals/NNN-*.md
.gitignore   *.bz2 *.tar *.sqlite* *.jsonl exports/ run/ screenshots/ (synthetic ones under docs/synthetic/)
```

The repo root holds no top-level `.py` file; a test enforces this. That matters because discovering tests with `-t .` puts the root on `sys.path`.

### 3.5 Dependency on betangel-research

The pin is a **read-only, network-free local clone**:

1. `bin/suite vendor <full-sha>`, which runs `tools/vendor_research.py`, is run by hand: by lab-Claude, never automatically. The launcher checks the run marker first (section 6.8). Run directly, `tools/vendor_research.py` refuses with `launcher_required` (exit 2) before it arms the guard, runs git or makes anything, so that check cannot be skipped (Astra's PR #1 review, item 5; lab-Claude's decision of 2026-10-17, which took the refusal of the two fixes Astra offered: the launcher also fixes the interpreter, clears the environment and checks `TMPDIR`, which a second entry would have to copy; 9e6dfce). Before any git call or mkdir, it refuses `research_clone_on_path` when the deps root, the pin directory or the checkout lies in `~/betangel-research`. The check is by name or by identity (`st_dev`/`st_ino`), at the nearest existing ancestor, so a link spelled through the firmlink is seen too. It is repeated just before the clone, and the guard refuses a partial clone path in the clone as well (Nuance's PR #2 review, item 2; e51b469). A clone that cannot be stat()ed for any reason but a missing name (no search permission, a link loop) cannot be judged, and is refused the same way (26fb4c4), and so is a path that cannot be stat()ed for such a reason, such as one through a directory with no search permission that holds a link into the clone (4ddf966). Every git call runs with exactly `guard.VENDOR_GIT_ENV` plus HOME; the guard refuses an inherited or any other environment (item 10; 816e832). That environment turns replace refs and grafts off (`GIT_NO_REPLACE_OBJECTS=1`, `GIT_GRAFT_FILE=/dev/null`): either would make a dangling commit look like an ancestor of main to `merge-base --is-ancestor`. Every call also has `-c core.attributesFile=/dev/null`, so the user's `~/.config/git/attributes`, which `GIT_CONFIG_GLOBAL` does not cover, cannot change the bytes checkout writes and `--bump` pins (lab-Claude's round-4 review; 7dc20d7).
   1. It runs `git -C ~/betangel-research cat-file -e <sha>^{commit}`, a read-only object lookup. If the commit is not there yet, it stops and asks you to wait for the Air's fast-forward. It never fetches. Then `git -C ~/betangel-research merge-base --is-ancestor <sha> refs/heads/main`, also read-only: only a commit on the research main branch can be pinned, otherwise vendor refuses with `commit_not_on_main` (Nuance's PR #2 review, answering Q-N2: "cat-file -e accepted unmerged and dangling commits"; 1d23fdc).
   2. `git clone --no-checkout --no-hardlinks ~/betangel-research ~/.local/share/betangel-suite/deps/betangel-research-<sha12>.partial`, a local clone with no network.
   3. `git -C <dir> checkout --detach <sha>`, then `git -C <dir> remote remove origin`, so no later command can fetch from the moving clone.
   4. Compute the sha256 of every allowlisted file (section 4.1) plus `research/experiments/backtest-p0-bsp-v1.json`, which holds the month roles. Write them into `pin/betangel-research.json` (on a pin bump) or check them against it (on a fresh machine).
   5. Rename the directory into place and `chmod -R a-w` the working tree. Before the pin is hashed (step 4), and again after the rename, before the first chmod, a pre-pass over the whole tree checks that it is a real directory outside the clone, holding only directories, symlinks and regular files with one link (`deps_link_present`). chmod never follows a link (Nuance's PR #2 review, item 8; 7357273). A refusal by the second pass leaves the renamed directory as it is, still writable: a re-run refuses the same way, and `activate()` reads only the pinned files, each refused unless it is a regular file with one link, so no safety is lost (Nuance's PR #2 re-review, F10, which corrected this item's earlier "before any chmod and the rename"; the tool's docstring in 9e6dfce).
2. **Rules.**
   - Never `git worktree add`, which would write into the deploy clone's `.git`.
   - Never a submodule over the deploy key.
   - Never `sys.path` pointing at `~/betangel-research`. `pin` judges the deps root and every `sys.path` entry through `roots.lies_in`, by text and by identity, stat calls only: a clone or an entry that cannot be stat()ed for any reason but a missing name is refused, and an empty entry is judged as the current directory, which is what the import system reads it as (Nuance's PR #2 re-review, F11; Astra's re-review of PR #2, judgement items; c00461c).
3. **Why a clone and not `git archive`.** A real checkout lets the upstream offline suite run in its native layout on a pin bump: some of its tests check the real checkout only when the tree is one (`support.IN_GIT_CHECKOUT`, for example tests/test_betfair_paths.py:85). Nuance answered Q-N2: "Keep the network-free clone after 2 and 10" (Nuance's PR #2 findings 2 and 10, both fixed: e51b469, 816e832). Either way nothing is written into `~/betangel-research`.
   - **Dropped reason** (Nuance's PR #2 review: "Drop 3.5 item 3's git_state reason (11); keep the upstream IN_GIT_CHECKOUT one"). This item used to say that the clone lets the oracle `run_paper_replay` record a `git_revision` through `receipts.git_state`. Under the test guard, `git_state`'s `GuardRefusal` escapes its `except` (receipts.py:128-146), so the parity test stubs it instead (section 4.2).
4. **At startup.** `pin.py` checks the files against `pin/betangel-research.json` and refuses with `pin_mismatch` if they differ; hashing about 25 files takes a few ms. No git runs at startup. Then:
   - it never puts the deps directory on `sys.path` (Nuance's PR #2 re-review, F1; Astra's re-review of PR #2: "remove it in a reviewed tightening"; 3f86e34). Until round 5 it appended it, so after `seal()` any other top-level name in the deps tree loaded unhashed: `scripts.backup_metadata`, a planted module, and the standard library's probes for modules that macOS lacks (`nt`, `_winapi` and `_wmi` on 3.13, `org` on 3.11), which reached the deps directory during a plain import of `rx`. The closure finder (below) gives each of the 25 its spec at its pinned file, by name, so no other deps-tree name is found;
   - it asserts that `Path(betangel_research.__file__).resolve()` lies inside the deps directory;
   - each pinned file is opened below the deps directory with `O_NOFOLLOW_ANY` through `dir_fd` (a component walk where the flag is missing), with `O_NONBLOCK`, and is refused unless it is a regular file with exactly one link (Nuance's PR #2 review, items 8 and 22; e4ddc18);
   - `activate()` puts a `meta_path` finder first. From then on only the 25 closure modules can be imported from `betangel_research`, only from their pinned files, and only from bytes that match the pin at load time. Any other `betangel_research` name is refused with `upstream_import_refused`, however it is imported (item 7; 08af945). A test checks that the pinned files import only the closure and the standard library: it flags every name whose top-level part is not in `sys.stdlib_module_names`, not only `betangel_research` names (AST; 923c1de, widened in 3f86e34).

   `receipts.code_hashes` covers only the package root and `betfair/*.py` (receipts.py:121-125), which is why the suite hashes `backtest/*.py` itself.
5. **Pin bumps.** A bump is a suite PR. It lists the diff of allowlisted files and runs:
   - the contract test (section 4.5);
   - the upstream offline suite at the new commit, from the deps clone: `PATH=/opt/homebrew/bin:$PATH BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 python3.13 -B -m unittest discover -s tests`, never during an announced Nuance run;
   - the suite's own tests.

   Nuance reviews every bump that changes an allowlisted file. "Allowlisted file" means every `PINNED_FILES` entry, the month-roles JSON included (Nuance, Q-N2).
6. **The pin stays at 76f71dc (Nuance, Q-N2).** Nuance found that up to 041461a only the P0 JSON changed, that its population is equal, and that no suite code reads it. A bump is made only when a closure module the suite needs, or the month roles, change.

### 3.6 Launcher and Python version policy

`bin/suite` is the only way to run the engine and the tests. It does the SSH checks **before** `env -i`, because `env -i` drops `SSH_ORIGINAL_COMMAND` and `SSH_CONNECTION`. It then passes a validated flag through.

```sh
#!/bin/sh
# Fixed interpreter, isolated mode (-I), no site-packages (-S), no bytecode (-B), network forbidden.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
VIA_SSH=0
case "${1:-}" in
  ssh-session)   # only as the viewer key's forced command: inside SSH, with no requested command
    [ -n "${SSH_CONNECTION:-}" ] || { echo "refused:ssh_session_outside_ssh" >&2; exit 2; }
    [ -z "${SSH_ORIGINAL_COMMAND:-}" ] || { echo "refused:ssh_original_command" >&2; exit 2; }
    VIA_SSH=1 ;;
  open|serve)
    [ -z "${SSH_CONNECTION:-}" ] || { echo "refused:open_over_ssh" >&2; exit 2; } ;;
esac
for a in "$@"; do
  [ "$a" != "--print-url" ] || [ -z "${SSH_CONNECTION:-}" ] || { echo "refused:print_url_over_ssh" >&2; exit 2; }
done
case "${1:-}" in
  test|uisnap|vendor|stop) TMP="$HOME/.local/state/betangel-suite/tmp" ;;   # their own guard modes, never the suite root
  *)                       TMP="$HOME/betangel-data/suite.noindex/tmp" ;;   # created 0700 after the run-marker check
esac
PY=/opt/homebrew/bin/python3.13   # `bin/suite test --py311` runs the same tests on python3.11
if [ "${1:-}" = test ] && [ "${2:-}" = --py311 ]; then PY=/opt/homebrew/bin/python3.11; fi
exec /usr/bin/env -i HOME="$HOME" USER="$USER" LANG=en_GB.UTF-8 PATH=/usr/bin:/bin \
  TMPDIR="$TMP" SQLITE_TMPDIR="$TMP" SUITE_VIA_SSH="$VIA_SSH" \
  BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 \
  "$PY" -I -S -B "$ROOT/bin/_launch.py" "$@"
```

- **The SSH checks catch accidents, not a determined same-uid process.**
  - The Air agent key is a full shell with no forced command, so `SSH_ORIGINAL_COMMAND` is unset there too.
  - These checks stop `open` or `--print-url` from running over SSH.
  - The rest rests on the agent-conduct rules (section 3.9, rule 6).
- **`-I` and `-S`.**
  - `-I` implies `-P`: neither the script directory nor the cwd is put on `sys.path`. So `_launch.py` appends the repo root itself. `pin.py` puts nothing on `sys.path`: its closure finder loads the 25 pinned modules from the deps clone (section 3.5, item 4).
  - `-S` drops Homebrew's `site-packages`, so a stray package there cannot shadow `betangel_suite` or `betangel_research`.
  - The suite and betangel-research are stdlib-only. Upstream checks this for `betfair/*.py` at tests/test_betfair_boundaries.py:297 and for the backtest package at tests/test_betfair_backtest_boundaries.py:949.
- **`env -i`.** Drops any inherited `BETFAIR*`, `BETANGEL_BETFAIR_*`, `PYTHON*` or `SSH_*` variable. Only `BETANGEL_BETFAIR_FORBID_NETWORK=1`, `TMPDIR`, `SQLITE_TMPDIR` and `SUITE_VIA_SSH` are set.
- **Temporary files.**
  - `env -i` would otherwise leave `tempfile.gettempdir()` at `/tmp`.
  - Homebrew SQLite 3.54.0 is built with `TEMP_STORE=1`, so large sorts can spill temp files to SQLite's search path. Those would be licensed derivatives outside `~/betangel-data`, opened in C where the audit hook cannot see them.
  - So `TMPDIR` and `SQLITE_TMPDIR` point at a 0700 directory inside the suite root, created only after the run-marker check (section 6.8). `test`, `uisnap`, `vendor` and `stop` run in guard modes of their own (`cli.OWN_MODE_COMMANDS`), none of which has the suite root as a write root, so theirs is the state root's `tmp/` (`roots.STATE_TMP_COMMANDS`; `stop` joined them in 8102f99). `stop` and `vendor` make no temporary files, so `cli.main` creates none for them (`cli.NO_TMPDIR`; 96d0bcc).
  - And the guard's `sqlite3.connect` wrapper sets `temp_store=MEMORY` on every connection, and refuses one where it does not then read 2 (`sqlite_connect_refused`). The hook refuses `connect("")` (`sqlite_connect_refused`), because that private database is itself a temporary file, opened before the setting. Otherwise SQLite would fall back to `/var/tmp` or `/tmp` if `TMPDIR` were gone (Nuance's PR #2 review, item 15; 06dba20).
- **Python 3.13 is primary.** Tests also run on `/opt/homebrew/bin/python3.11`, matching the upstream syntax floor.
  - The engine refuses to start on any other major version, and in particular on 3.15. It is refused because 3.15 is frozen for Nuance's certification, and so that one interpreter (3.13, with 3.11 as the floor) is the tested one.
  - Nothing installs or upgrades an interpreter. `session.json` records the interpreter version.
- **Tests.** `bin/suite test` runs `python3.13 -I -S -B -m unittest discover -s tests -t .` from the repo root under the same environment, then `~/.local/bin/node --test ui/tests` (section 11 for the fast and heavy tiers).

### 3.7 State roots (R-4 agreed by Yu; Nuance's agreement, Q-N3: as built at 52a9edc, on conditions, to be confirmed at the merge SHA)

| Root | Mode | Contents | Licensed? |
|---|---|---|---|
| Indexed data roots, for example `~/betangel-data/historic-pro` (Nuance's, read-only to the suite) | as is | raw, manifests, index | yes |
| `~/betangel-data/suite.noindex/` (the **suite root**) | 0700 | `catalogue/<index_head_sha256>.sqlite`, `sessions/<YYYY>/<MM>/<session_id>/{journal-paper.sqlite, commands.jsonl, session.json, report.json}`, `ledger/viewed-markets.jsonl`, `reports/` (problem reports, codes only), `exports/`, `logs/` (codes and counts only), `private/` (full tracebacks, later; none is written in Phase 0; agents never read it), `tmp/` | derivatives: yes |
| `~/.local/state/betangel-suite/` | 0700 | `config.json`, `prefs.json` (UI preferences only), `install-salt` (0600; section 9.2, item 9), `salt-provisioned` (0600; the salt's first-provisioning marker, section 9.2, item 9), `run/{engine.lock, realdata.lock, engine.pid, STOP, control.sock, interrupted/}` (`interrupted/` holds code-only end notes; section 7.10), `tmp/` (synthetic tests) | no |
| `~/.local/share/betangel-suite/deps/betangel-research-<sha12>/` | read-only | pinned upstream code | no |
| `~/.local/share/betangel-suite/app/<sha12>/` + `current` symlink | read-only | the reviewed release copy that every command Yu runs uses (section 8.6) | no |

- **Rules for the suite root:**
  - it must pass `archive.check_data_root` (archive.py:273): outside the repo and every worktree;
  - every derived path goes through `path_guard.guard_path` (path_guard.py:58; `prospective=True` for new files), which refuses the repo's live-state and certificate trees. The suite never reads the deny list itself; it uses only `guard_path`, `PathDenied` and `denied_sequence` (path_guard.py:25-27);
  - a single writer helper refuses any write outside the roots above.
- **Placement** (Nuance's PR #2 review, item 1; 62c39c6, 851885a). The roots check trusts each root's real path, so the file system must not put a root where the text does not say:
  - the suite root must be a real directory, or missing, at exactly `realpath(~/betangel-data)/suite.noindex`. A `suite.noindex` that is a link is refused (`suite_root_misplaced`);
  - every other write root, and `TMPDIR`, must not equal, lie in or contain `~/betangel-data`. This is judged by casefolded realpath and by `(st_dev, st_ino)`, walking ancestors with `..`, both ways, with stat calls only (`root_overlaps_data_home`). A stat that fails for any reason but a missing name cannot be judged, and is refused too (57fc0c9);
  - every write root, and `TMPDIR`, must also not equal, lie in or contain the run marker's directory, `~/.local/state/lab-runs`, judged the same way, stat calls only (`root_overlaps_lab_runs`). A state root linked to `~/.local/state` took `lab-runs/` into the roots, and with it the removal of `ACTIVE` and the renaming of the wrapper's `LOCK` (Nuance's PR #2 re-review, F5; c3b0c61);
  - `guard.arm` checks every write root of the mode and `TMPDIR`, in every mode; the writer helper checks the root of each path it writes;
  - no name from a root down to `TMPDIR` may be a link (`tmpdir_mismatch`; 8d0955d), nor `run/` or `run/realdata.lock` (`run_lock_invalid`; b0d5c0d), so each is where its text says. Links above a root stay allowed;
  - the hook refuses a symlink, hard link or rename that puts a name where a root, `TMPDIR` or a directory between `TMPDIR` and its root is, or moves one away (`root_replace_refused`; 8d0955d for the directories between);
  - so every `arm()`, the test runner's included, stats the `~/betangel-data` entry; the engine also lstats `suite.noindex`, and the realpath walk of a linked root stats the names on the link's path, before refusing it. These are stat calls only: nothing there is opened or listed. Nuance's answer to lab-Claude's question 7 of 2026-10-17 (PR #2 re-review): "Yes, within rule 5". This item's earlier "never what is in it" was wrong, as Nuance's answer points out.
- **`run/realdata.lock`** (section 6.8) is made once (0600) and never unlinked. The guard refuses removing, moving or replacing it (`run_lock_protected`; 18de53e), and `arm()` refuses a `run/` or lock that is a link (`run_lock_invalid`; b0d5c0d).
- **Never touched:**
  - `~/betangel-data/lab-state`, `~/betangel-data/logs`, `incoming/`, and anything under a data root for writing;
  - `~/Library/Application Support/betangel-research/betfair` and `~/.config/betangel-research`;
  - the Keychain.
- **Nuance's conditions (Q-N3).** Nuance agreed the suite root on three conditions (PR #4 review, 2026-10-16):
  1. Nuance never uses `~/betangel-data` or `suite.noindex` itself as a data or lab-state root.
  2. Before Phase 1a, the suite refuses a data root that equals, contains or lies inside `suite.noindex`, `lab-state` or `logs`, or that lies inside `incoming/`. It compares roots by file identity, not by path text. **Owed before Phase 1a** (section 5.2); Phase 0 reads no data root.
  3. The marker half is agreed first. Nuance agreed it in the same review; Nuance's PR #2 review makes both halves conditional again (section 6.8; Q-N3).
- **The root half, after Nuance's PR #2 item 1.** Nuance's words: "agree the root half after 1". Item 1 (roots that resolve into `~/betangel-data`) is fixed on this branch by the placement rules above (62c39c6, 851885a). Nuance's PR #2 re-review agrees the root half as built at 823c194, pending F4 and F5 (below). `roots.STATE_ROOT_AGREED` stays True meanwhile. That is lab-Claude's call, which Nuance accepts on conditions (below): with the fix, the engine refuses a misplaced suite root, and no Phase 0 command reads a data root.
- **The flag.** `roots.STATE_ROOT_AGREED` is True, and `bin/suite`'s default `TMP` branch is the suite root's `tmp/` (section 3.6). The two change together; `_launch.py` refuses a mismatch (`tmpdir_mismatch`). Only the engine's guard mode has the suite root as a write root: the test runner, `vendor`, `uisnap` and `stop` never write under `~/betangel-data`, and in their modes the guard refuses reads there too (section 10, "The guard's scope"). Tests use temporary HOMEs. The first engine command run with the real HOME creates `~/betangel-data/suite.noindex/` (0700) and its `tmp/`, after the run-marker check.
- **Why `~/betangel-data/suite.noindex`.**
  - It sits beside the data roots, so Nuance's discovery never sees it. That discovery is `archive_shas(root)` over `<root>/manifests` (market_index.py:927).
  - The `.noindex` suffix keeps Spotlight from indexing the suite's text derivatives (CSV exports, `session.json`, `report.json`, `commands.jsonl`). Yu is also asked to add all of `~/betangel-data` to Spotlight Privacy (Q-Y15), which Nuance called sensible (mailbox 08:57Z, B3).
  - Checkpoints and replay buffers live in memory only, which keeps on-disk derivatives to the catalogue, journals, ledger, reports and exports.
- **Nuance's agreement, as built** (Nuance's answer to lab-Claude's question 8 of 2026-10-17, PR #2 re-review). Nuance agrees the root half and the marker half of Q-N3 "as built at 823c194, pending F4/F5" (section 6.8). Nuance also accepts `roots.STATE_ROOT_AGREED=True` on the unmerged branches, labelled as lab-Claude's call, "because on #2 no implemented command writes the suite root". Nuance's conditions, in Nuance's words: "no merge with the flag True unless my agreement is recorded at the merge-candidate SHA; any later change to placement/runmarker/root-lock protection reopens the re-check; until then no engine command runs on the lab with the real HOME." F4 and F5 are fixed on this branch: F4 in ff35218 (fresh loads of `_posixsubprocess`; section 10, I-5) and F5 in c3b0c61 (`lab-runs/`; "Placement", above). c3b0c61 changes placement, so by Nuance's second condition the re-check is open again, now at the merge-candidate SHA (lab-Claude's reading).
- **Nuance's agreement at 52a9edc** (Nuance's review of PR #5 at 52a9edc, 2026-10-19). In Nuance's words: "Q-N3: I agree both halves, root and marker, as built at 52a9edc." Nuance's conditions, quoted from that review:
  - (a) "The merge carries this SHA's Q-N3 file set unchanged. The set is: runmarker.py; the roots placement and writer; the guard's placement, run-dir and run-lock checks; cli's REALDATA_COMMANDS and the order in main; the launcher's marker order; the TMP lines in bin/suite; config's run_marker, state_root and data_roots; and the marker checks in engine, server and sshsession." Under this condition Nuance's agreement carries to the merge SHA, and Nuance confirms it there in one line. "A fix that touches the set reopens only its own diff. The comment-only N3-S1 fix does not reopen it." (N3-S1 is Nuance's finding on stale "not answered" comments, fixed on phase0/foundation.)
  - (b) "No engine runs with the real HOME on the lab until three things hold: a new C0 carries 416702f's L1; every runbook block has a marker step (mine to add); and Yu has settled state_history (RS-13). No suite command runs between that L1 and 5a." (RS-13 is in proposal 003.)
  - (c) "Before 1a reads any data root, two things are needed: my identity checks (condition 2), and the marker and lock bound to the same home as the data. config.py:104-119 accepts absolute data_roots."
  - (d) "I fix N3-W1 and N3-W2 before my next wrapper job." Both are on Nuance's side: Nuance's wrappers are to hold `LOCK_EX` on `realdata.lock` for the whole job and adopt `lab-runs/LOCK`, as section 6.8 describes, and a `pgrep` check that never matched a suite command is to go.
- **The runbook's L1 layout check** (upstream, in betangel-research's runbook; not the suite's later L1 shell). As Nuance describes it, L1 requires `~/betangel-data` to hold only `historic/` (and `lab-state/` after the runbook's 5a). So the suite root, which the first engine command run with the real HOME creates, would make the lab fail L1 (lab-Claude's question to Nuance, 2026-10-17). Nuance chose option (a) (Nuance's mailbox note of 2026-10-18): L1 will also accept `suite.noindex/` and `historic-pro/` as known, optional entries in `~/betangel-data`, which keeps licensed derivatives inside the one directory that the deny rules and Nuance's wrapper guard. It is an upstream runbook change, authored by Astra and reviewed by Nuance, in the next tooling round. Nothing runs L1 until a new C0, so `historic-pro/` existing now blocks nothing (Nuance). Nuance's earlier request to keep new files out of `~/betangel-data` still holds for everything but those two roots.
  - **Until the widened L1 lands, no engine command runs with the real HOME** (lab-Claude's decision of 2026-10-19), because the first one would create the suite root and make the lab fail L1. This adds to Nuance's conditions above; section 16 lists it as a risk.
  - **What "lands" means here** (Nuance's review of PR #1 at af960fd, F4; lab-Claude adopts it): the lab's betangel-research checkout is at a C0 that includes 416702f (betangel-research PR #28, which widened L1 and is on its main since 2026-10-19), and no suite command runs between that C0's L1 check and the runbook's 5a. Nuance's condition (b) above says the same. Sections 3.8, 12 and 16 use "lands" and "has landed" in this sense.

### 3.8 Configuration

`~/.local/state/betangel-suite/config.json`, with defaults in `betangel_suite/config.py`:

| Key | Default | Notes |
|---|---|---|
| `data_roots` | `[]`. `["~/betangel-data/historic-pro"]` (the root Nuance named, Q-N4, ingested and indexed on 2026-10-19, section 2.4) only from Phase 1a, once data roots may be read (section 5.2) and the runbook's widened L1 check has landed on the lab, as section 3.7 defines it | Each must pass `archive.check_data_root`. With no root, the engine runs synthetic mode only. The BASIC root is used only by explicit counts-only commands (section 5.1). |
| `state_root` | `~/betangel-data/suite.noindex` | R-4 (Yu); Q-N3 (Nuance: agreed on three conditions in Nuance's PR #4 review, conditional again since Nuance's PR #2 review; section 3.7) |
| `port` | 8765 | loopback only |
| `frame_hz` | 10 | 5-20 |
| `cap_profile` | `v1-live-mirror` | or `practice` (section 7.2; R-7) |
| `commission_source` | `user_package_unverified` today; `user_package_verified` through a reviewed change before Phase 1b, following R-3 (Yu's words as relayed by Nuance on 2026-10-18; confirmed by Yu in Yu's own hand on 2026-10-19; section 2.2.1) | R-3 |
| `research_months_ruling` | `null` | A ruling id. While it is null, research months are hidden and not written to the catalogue (section 5.3). It stays null until Yu answers Q-Y7; no ruling id is accepted before then (Nuance, PR #1 review). Only null loads until a reviewed PR adds the ruling id to `config.ACCEPTED_RULINGS` (empty now), after Yu rules on Q-Y7 with Nuance and Astra; a config edit alone is refused (`config_invalid_value`; Nuance's PR #2 review, item 12; 3f51ae7). |
| `run_marker` | `~/.local/state/lab-runs/ACTIVE` (Q-N3: agreed by Nuance in Nuance's PR #4 review; conditional again since Nuance's PR #2 review; agreed as built at 823c194 in Nuance's PR #2 re-review, pending its findings F4 and F5; agreed as built at 52a9edc in Nuance's review of PR #5, on conditions, to be confirmed at the merge SHA) | section 6.8 |
| `watch_grace_s` | 600 | pause-unless-watched grace (section 8.6) |

- **Reading `config.json` and the install salt.** Both are opened with `O_NONBLOCK`, and `fstat` judges them before any read, so a FIFO in either place is refused at once (`config_insecure`, `salt_invalid`; Nuance's PR #2 review, item 22; 53239a3). The pin's own reads do the same (e4ddc18).
- **Paper config.** It is `deepcopy(config.DEFAULTS)` (config.py:27-72), with the active cap profile merged in, plus:
  - `orders.paper.commission_rate = 0.02` and `commission_source`;
  - `orders.customer_strategy_ref` set to the ref the journal intents use: `suite-click` for operator sessions and `suite-test` in synthetic test mode.
  
  So V11 (validate.py:171-173), the config hash and the journal all agree. The DEFAULTS value is `bar-manual` (config.py:57), and the journal fold takes the ref from the intent (journal.py:620, :752).
- **Validation.** It is checked once at startup by the repo's own `config.validate_config` (config.py:254), against `paths.StatePaths(home=<suite root>/repo-home, root_override=<suite root>/repo-home/state)`. That override is accepted only with FORBID_NETWORK set (paths.py:58-72). Nothing is created; `StatePaths` creates directories only in `ensure()`. Nuance's conditions (Q-N8): the suite root is agreed and exists first, else the validation refuses with `subprocess_refused`; and this `StatePaths` object feeds only `validate_config`, because its `kill_engaged()` would be a false all-clear.
- **Git calls during validation.** Validation spawns `git -C <dir> rev-parse --is-inside-work-tree` through `paths.require_outside_worktrees` (paths.py:149, :158; config.py:224-236). In Phase 0 the engine refuses that probe: no Phase 0 path runs validation, and the guard never judged the probe's environment (I-5; Nuance's review of PR #2 at 4fa5835, N5-1; 16df724). If validation is wired later, the probe comes back with an exact environment and an engine-mode test of its own, as `guard.py`'s limits say (section 10, I-5).
- **Recorded as a hash only.** The validated config is never written whole into `session.json`, `report.json`, a journal note or `commands.jsonl`; only its `canonical_sha256` is. The reason is that every upstream writer the suite reuses runs `secret.refuse_forbidden` (journal.py:289; receipts.py:183, :211). That raises `SecretLeak` for any key, at any depth, that normalises to `session`, `token`, `headers`, `authorization`, `cookie`, `appkey` and similar (secret.py:114-133), and `config.DEFAULTS` has a top-level `session` section (config.py:41).

### 3.9 Development workflow and the suite's AGENTS.md

- **Branches and PRs.** Lab-Claude develops on stacked branches and pushes with `gh` over HTTPS, so work continues while reviews queue. Review routing is proposed up front (Q-N12); who merges is Q-Y8 (section 2.2.1). The table in AGENTS.md is the binding copy:
  - Astra reviews `guard.py`, `rx.py`, `errors.py`, `release.py`, `runmarker.py`, `api/`, the launcher (`bin/suite`, `bin/_launch.py`), the boundary tests, the hygiene scanner (`tools/hygiene_scan.py`, `tools/pre-commit`, `tools/pre-merge-commit`, `tools/commit-msg`, `tools/pre-push`, `.gitignore`) and pin bumps;
  - Astra also reviews `cli.py`, uisnap (`betangel_suite/uisnap.py`, `tools/uisnap/`) and the staged scripts (`tools/stage/`). This row is lab-Claude's proposal, from Phase 0c's review plan; Nuance did not ask for it. It only adds a reviewer. It stays open for Yu to rule on with Nuance (Q-N12, Q-Y8). `tools/stage/` is also a rule document, so the governance row (below) sends it to Nuance and Astra either way;
  - Nuance reviews the data and paper paths (`data/`, `paper/`, `replay/`), the synthetic generator (`synthetic.py`, `tests/fixtures/`), the tick export (`tools/export_ticks.py`, `ui/ticks.json`), and every pin bump that changes an allowlisted file;
  - Astra and Nuance review `engine.py` and the roots (`roots.py`) jointly;
  - Astra and Nuance also review `config.py`, `docs/data-handling.md` and `tests/__init__.py` jointly (the Q-N12 additions in Nuance's PR #2 review). This row only adds reviewers;
  - **Rule documents go to Nuance and Astra, accepted at the same named head SHA.** Binding: the governance row Nuance recommended (PR #1 review, item 9, amending Nuance's view on Q-N12), adopted by Yu on 2026-10-17 ("Lets go with what you recommended for all :)"; section 2.2.1). The rule documents are AGENTS.md, this document, `docs/data-handling.md`, `docs/proposals/` and `tools/stage/`. A change of meaning in one follows rule 10, and so goes to Yu, unless both Nuance and Astra say it does not widen. Changes to AGENTS.md's rules or routing also need Yu's approval (Nuance's PR #2 review: "changes to AGENTS.md's rules or routing also need Yu"; adopted with the row);
  - **UI-only PRs merge on Yu's acceptance alone.** Binding: answered by Yu on 2026-10-17 ("Lets go with what you recommended for all :)"; section 2.2.1). This section's definition was "`ui/` with no change to routes, the command enum or `ui/ticks.json`", which does not say whether the diff may touch files outside `ui/`. Lab-Claude's reading (lab-Claude's, not Yu's words; Yu can override it): a UI-only PR is one whose diff touches only files that change how pages look, the `ui/` static assets, with no change to routes, the command enum or `ui/ticks.json`, and no change to `api/`, the engine, `guard.py`, `roots.py`, a rule document or a test of any of those. A PR that also touches a rule document is not UI-only; the rule-document row applies to it;
    - **UI-only, narrowed: the order-sending paths of `ui/` go to Astra.** Binding: answered by Yu on 2026-10-17 ("ohh understood. Yes lets go with what you recommended"; section 2.2.1), on Nuance's PR #1 re-review, finding 3, which amends Nuance's own answer to Q-N12. The rule against automation lives only in `ui/` JavaScript (section 8.3), so under the definition above alone a `ui/`-only PR could add an automated order send with only Yu's review. So UI-only excludes the code that sends commands (command call sites and the sender in `ui/stream.js`), the keyboard shortcuts that trigger orders (command keymap entries), the access-token handling, and timer paths that lead to the sender. Changes to those go to Astra, and to Nuance as well for paper-trading keys, and `tests/test_ui_assets.py` goes to Astra. Everything else in `ui/` that only changes how pages look goes in on Yu's acceptance alone. The node tests behind the rule are owed before 1b (section 8.3), and section 9.4 gives the residual;
  - **Any file no other row names goes to Yu** and waits for Yu's acceptance: the fail-closed row. Binding: part of the governance row Yu adopted on 2026-10-17, in Nuance's own item 9 text, which sends "uncovered diffs" to Yu (section 2.2.1). Until then this row sent such files to Astra and Nuance jointly: lab-Claude's reading of the "fail-closed row for unnamed files" in Nuance's PR #2 review, which names no reviewer. Yu's ruling supersedes that reading, so the question put to Nuance on 2026-10-17 about it is moot. Nuance has since withdrawn the "fail-closed row for unnamed files", which "named no reviewer, so disagreed with item 9; my slip" (Nuance's answer to lab-Claude's question 1 of 2026-10-17, PR #2 re-review);
  - **A test file goes to the reviewers of the modules it imports, else Yu.** Binding: answered by Yu on 2026-10-17 ("yes lets go with what you recommended"; section 2.2.1). It is the mechanical form Nuance recommends: "a test → the reviewers of the modules it imports, else Yu" (Nuance's answer to lab-Claude's question 1, PR #2 re-review, which left the row "Yu's to decide"). A test that imports no routed module goes to Yu. Lab-Claude first proposed sending each test file to the reviewers of the code it tests; on 2026-10-17 it put the mechanical form, and the UI-only narrowing above, to Yu, recommending yes to both.
- **Merging.** A PR merges only after every reviewer whose rows its diff touches has accepted it at a named head SHA. Lab-Claude merges.
  - The merge rule is Nuance's condition for Q-N12 ("agree once amended"; PR #4 review, 2026-10-16), with the joint row for `engine.py` and the roots and the additions to Nuance's own row. Nuance's PR #2 review sends "Every touched reviewer accepts the same head SHA" to Yu as a Q-Y8 clarification; Yu's 2026-10-16 answer is in section 2.2.1.
  - Who merges is Yu's 2026-10-16 answer to Q-Y8, "Its all good :) Merge when sensible", read as section 2.2.1 records. That reading, labelled there as lab-Claude's and not Yu's words, also requires the tests to pass on 3.13 and 3.11 at the accepted SHA. Yu can override it.
  - A PR that changes AGENTS.md's rules or routing also needs Yu's approval of those AGENTS.md changes before it merges, in addition to its reviewers (the governance row, adopted by Yu on 2026-10-17). #2, #4 and #5 all change them, so each also waits for Yu's approval of its AGENTS.md changes (section 2.2.1).
  - **Every PR in the sitting lands with `gh pr merge --merge`** (Nuance's PR #1 review at af960fd, F2, and Nuance's review of PR #5 at 52a9edc, N5-2; lab-Claude adopts the fix). No fast-forward, rebase-merge, squash or direct push to main. The reason is release's first-parent check (section 8.6): it keeps side-branch commits off main's first-parent line only if each PR lands as a merge commit. The stack is linear from main, so a fast-forward would put every interim commit on that line, and main could not be corrected later without rewriting it. Setting the GitHub repository to allow merge commits only is a repository setting for Yu: asked of Yu, not done (section 2.2.1).
- **Collab.** Edit tasks use `root_path=/Users/user/betangel-suite`.
- **Upstream changes.** Any betangel-research change goes to Nuance as a proposal (section 14).
- **Yu's feedback channel.** Yu's acceptance and feedback reach lab-Claude only in a lab-Claude session that Yu types into (on the lab, or one Yu opens from the Air).
  - An acceptance checklist file that Yu edits is a log of Yu's checks, not acceptance in itself (Nuance, PR #1 review).
  
  Relays from Nuance or the mailbox are context, not acceptance.
- **The suite's AGENTS.md (binding on every agent):**
  1. **Paper-only MVP.** No credentials, Betfair API, network or live code. Never a "temporary" live endpoint. Later live and Air code never lives in this repo.
  2. **Imports.** Only `rx.py` imports betangel_research, and only from the allowlist.
  3. **Orders.** Every paper order on real data is an operator click (the OperatorClick rule, section 7.1). Scripted orders (`TestOrder`) exist only in synthetic mode, which refuses every real data root. There are no rule-generated orders.
  4. **Licensed data.** Licensed data and its derivatives stay under `~/betangel-data`. Nothing licensed goes in git.
  5. **Agent conduct.** A model context counts as an upload. Agents (lab-Claude, Nuance, Astra) never put real rows, runner names, prices, market ids or per-market results into their context, Collab, the mailbox, PRs or issues.
     - Diagnostics print codes, counts, salted hashes and timings only.
     - Agents never read, search or list anything under `~/betangel-data` (the ledger `ledger/viewed-markets.jsonl`, `sessions/` and `private/` included), or the install salt (section 9.2, item 9). They use `bin/suite ledger-summary` and `bin/suite diagnose`. Deny rules that Yu approved on 2026-10-16 back this up for lab-Claude's Read and Edit tools (Q-Y9); whether they hold for Grep and Glob is unverified; Bash, Nuance's SSH shell and Astra are conduct only (section 9.4).
     - Debugging uses synthetic fixtures. Screenshots are of synthetic markets only (uisnap).
     - No agent captures the screen, on either machine, while a suite page or an `ssh lab-suite` window is open (section 8.6).
     - **Exceptions: none without Betfair's specific written agreement naming the provider** (Q-Y9, confirmed by Yu on 2026-10-17; section 2.2.1). Real fields reach a model provider only with Betfair's specific written agreement naming that provider, plus Yu's explicit OK each time, in Yu's own words, scoped to one problem report and named fields (section 8.7). Until such an agreement exists, exceptions are not available.
  6. **Commands agents never run.** Agents never run `open`, `ssh-session` or `--print-url`, and never send `attach` or `new_code` to the real control socket, `~/.local/state/betangel-suite/run/control.sock` (section 9.1); tests send them only to engines in temporary HOMEs. They never POST to `/api/v1/command` or `/api/v1/bootstrap` on an engine with real data roots. `serve` and `open` never print a bootstrap code; only `--print-url`, used by Yu, does. `stop` is allowed, because it only reduces activity.
  7. **Nuance's runs.** While the run marker exists, no suite engine or real-data command starts. The marker is a stop request: a command already running drains, stopping at its next checkpoint and releasing its locks, and Nuance's wrapper begins upstream work only once it holds those locks. So nothing in the suite writes under `~/betangel-data` during the upstream run itself (section 6.8). Only Nuance's run wrapper creates or removes `~/.local/state/lab-runs/ACTIVE` and its `lab-runs/LOCK`; tests use temporary HOMEs; a stale marker is reported with codes and cleared only by the wrapper, or by Yu in Yu's own words (Nuance's PR #2 review, item 13).
  8. **No credential fields.** The suite UI never has credential fields. Any login prompt inside it is an attack.
  9. **Live-key data.** Paper or practice never runs on live-key data (section 2.3).
  10. **Scope.** Every widening of scope goes through the proposal process (section 14). **Who judges a widening** (the governance row, adopted by Yu on 2026-10-17; above): a change of meaning in a rule document goes to Yu under this rule unless both Nuance and Astra say it does not widen.

---

## 4. Reused betangel-research interfaces

### 4.1 Runtime: only through `rx.py`

**Verified import closure.** Importing the allowlist below with `python3.13 -I -S -B` and FORBID_NETWORK loads 25 `betangel_research` modules (checked 2026-10-15; also imports on 3.11.17):

- the package roots, `stream`, `temporal` and `evaluation`;
- `betfair.{book, config, constants, errors, filters, journal, lifecycle, paper, paths, pnl, receipts, schemas, secret, ticks, validate}`;
- `backtest.{archive, contract, market_index, path_guard}`.

The closure loads no gateway, cli, auth, credentials, transport, api, esa, recorder, killswitch, arming, presence, reconcile, **risk** or **capability**. tests/test_betfair_boundaries.py:22 marks the last two `INTERNAL_ONLY`.

**Nuance accepted this closure (Q-N1, PR #4 review, 2026-10-16):** "Exactly 25 modules load, with no gateway, auth, credentials, transport, risk or capability module and no network module."

**Owed before Phase 1b (Nuance, Q-N1).** `rx.py` gains wrappers, so that:
- `StatePaths` is built only with explicit roots;
- `OrderJournal` is built only with `mode="paper"` and an explicit clock;
- `validate_place` always runs with `mode="paper"`.

`SystemClock` is no longer on the allowlist (Nuance, Q-N1): no suite code uses it, and the journal always gets the suite's `SimClock`.

The **upstream closure** loads no `socket`, `ssl` or `http`, and no `urllib` module but `urllib.parse`, which python3.11's own `pathlib` imports (string helpers, no network code; `tests/test_imports.py` allows exactly that, and on 3.13 none loads; Astra's PR #1 review, item 12). The suite's own server does load `socket` and `http`, which is why the audit hook polices them (section 10). `subprocess` is loaded through `receipts` and `paths`, which is why the hook polices it too. `guard.arm()` imports `subprocess` itself, first. So `subprocess` keeps the original `_posixsubprocess.fork_exec`, behind its own `subprocess.Popen` event, while the module attribute gets the guard's refusing wrapper (I-5; 56a2631). A fresh instance of `_posixsubprocess` would carry the original again, so once the wrapper is in place the hook refuses every fresh load of it (I-5; ff35218).

| Module | Interface (as used; signatures exact) | Citation | Suite use |
|---|---|---|---|
| ticks | `LADDER_CLASSIC`; `parse_money(text)`; `parse_price(text)`; `to_hundredths(v)`; `to_pence(v)`; `is_on_ladder(price_h)`; `tick_index`; `tick_offset(price_h, n)`; `ticks_between(a_h, b_h)`; `snap(price_h, direction)` | ticks.py:35, :46, :54, :95, :100, :105, :109, :115, :125, :130 | The 350 ladder rows (exported to the UI as JSON; a JS test checks them), click to price, integer pence and hundredths, and green-up snapping with an explicit direction. |
| constants | `MIN_BET_PENCE_GBP`; `CLASSIC_BANDS`; `MARKET_STATUSES`; `COMMISSION_SOURCES`; `ABSOLUTE_CEILINGS` | constants.py:136, :142, :158, :185, :197-217 | The £1 minimum, ladder bands, status labels, commission label, and cap-profile ceilings. |
| book | `MarketBookCache(*, key_type, app_key_slot, source)` (all required; the suite passes `"historical"`, `None`, `"recording"`); `.apply(msg)` returns the changed market ids; `.snapshot(market_id, *, unreliable_ok=False, stamp=None)`; `.stream_unreliable`; `.has_definition(id)`; `.markets()`; `.counters` | book.py:136, :139, :168, :402-466 (stamp :448), :158, :162, :154, :59-61 | Book reconstruction. Snapshots are taken lazily (section 6.2). Counters appear as counts in diagnostics. |
| book | `replay_market_time(value)` | book.py:68 | Countdown and jump marks from `marketTime`. |
| schemas | `BOOK_SNAPSHOT_KEYS`, `RUNNER_KEYS`, `SNAPSHOT_KEY_TYPES`, `INSTRUCTION_V1_KEYS`, `ORDER_STATES`, `UNRESOLVED_STATES`, `validate_book_snapshot`, `validate_instruction_v1` | schemas.py:18-23, :26, :32, :46, :51, :164, :222 | The contracts that frames and tickets are built against. Missing SP keys (:23) are why the SP tap exists. |
| validate | `validate_place(market_id, instructions, *, book, open_orders, config, mode, now_ns, probe=False, now_monotonic_ns=None, customer_ref=None, customer_order_refs=None)`; `validate_cancel(market_id, cancels, *, open_orders, kill_targets=None)`; `make_customer_ref(now_ns, rng)`; `make_customer_order_ref(now_ns, rng)`; `profit_ratio_ok(size_p, price_h)` | validate.py:290-291, :410, :46, :51, :67 (V9 :102-121; V0 :190-192; V5 :212-219; V6 :220-221; paper V10 :154-163) | Every click is checked against V0-V14 and refusals are shown in plain English. `mode="paper"` is always passed explicitly (it has no default). Refs come from a deterministic rng per session and click: `rx` passes upstream `lambda n: rng(n)`, so a falsy rng is still used and never falls back to `secrets`, and `rx` never draws from the rng itself (Nuance's PR #2 review, item 9; ec039db). Green-up feasibility. |
| paper | `PaperExchange(params, *, queues=None, state=None)`; `.place(orders, *, book, now_ms, refusal=None)`; `.cancel(orders, cancels, *, now_ms)`; `.advance(open_orders, *, prev_book, book, now_ms, gap=False)`; `.settle(orders, *, market_definition)`; `.queue_state()`; `.export_state()`; `.close_market(market_id, refs)` | paper.py:155-179, :342, :358, :428, :592, :181, :184, :259 | The fill model, driven directly (R-1). `queue_state()` feeds the queue-ahead display. Exported state plus the constructor re-seed traded high-water marks (section 7.4). |
| paper | `PAPER_MODEL`, `PAPER_ASSUMPTIONS`, `PARAM_KEYS`, `REPLAY_STATUS`, `book_time_ms(book)`, `paper_bet_id(ref)` | paper.py:30-57, :59-60, :62, :101, :141 | The "How fills work" panel quotes these verbatim. Every report carries `REPLAY_STATUS`. |
| lifecycle | `TRANSITIONS`; `PAPER_REFUSAL_CODES`; `PAPER_FAILED_CODES`; `transition(order, new_state, *, reason, fields=None)`; `classify_place_report(result, *, sent_refs, orders=None)`; `classify_cancel_report(result, *, sent_bet_ids, orders=None)` | lifecycle.py:39, :72, :74, :103, :243, :306 | Turns paper reports into legal journal moves. A dry-run `transition()` checks the suite-built close lapse and the pending-order withdrawal (section 7.6). |
| journal | `OrderJournal(path, *, mode, clock=SYSTEM_CLOCK, busy_timeout_s=30)`; `.append(kind, payload, *, ..., expect_head)`; `.anchor()`; `.verify()`; `.fold(*, now_ns, submitting_as_unknown=True)`; `JournalFolder(mode).apply(event)` and `.state(*, now_ns, submitting_as_unknown=True)`; `KINDS`; `INTENT_PAYLOAD_KEYS`; `INTENT_SOURCES`; `CLOCK_REGRESSION_NS` | journal.py:303, :313, :483, :437, :410, :444, :689, :726, :837, :80, :95, :97, :93 | One hash-chained paper journal per session, always constructed with the suite `SimClock`. Forgetting it would silently put the journal on wall time, so a test asserts it. An incremental folder is fed by the events `append` returns, and is always read with `submitting_as_unknown=False`, as `_simulate` does (paper.py:884). `state()["orders"]` is a dict keyed by ref (journal.py:842, :869-870). |
| pnl, evaluation | `order_pnl_pence(side, avg_price_h, size_settled_p, runner_result)`; `market_realized(orders, runner_results, *, commission_rate)`; `EXCLUDING_RESULTS`; `evaluation.settled_market_costs` | pnl.py:24, :38 (Rule-4 exclusion :53-54, dead heat :55-56, commission rounding :79-82), :15; evaluation.py:136 | What-If, settlement at 2%, the official exclusion, and the indicative Rule-4 figure (section 7.9). |
| config | `DEFAULTS`; `validate_config(config, *, paths)` | config.py:27-72 (orders :56, caps :58-62, rules :63, paper :65-66), :254 | The paper config and cap profiles, validated by the repo's own validator (section 3.8). |
| paths | `FORBID_NETWORK_ENV`; `network_forbidden()`; `overrides_allowed()`; `StatePaths(home=..., root_override=...)` | paths.py:22, :29, :36, :58-72 | Startup refusal without FORBID_NETWORK; the validation-only override. `.paper.lock` (:82) is never taken. |
| receipts | `utc_from_ns(ns)` (int only); `parse_utc_ns(text)`; `canonical_sha256`; `file_sha256`; `atomic_write_json`; `append_jsonl`; `strict_json_loads` | receipts.py:29-34, :52, :104, :113, :180, :208, :247 | The sim clock on the pt axis (always `ms * 1_000_000`, never a float), session hashes, atomic 0600 writes, and strict request bodies (duplicate keys and NaN refused). |
| secret | `register(value)`; `assert_clean`; `refuse_forbidden` (called by the writers above) | secret.py:20-25, :114-133 | The session token and bootstrap codes are registered, so a journal or receipt write that contains one is refused (journal.py:296; receipts.py:185, :214). |
| backtest.archive | `CHUNK_BYTES`; `LIMIT_CEILINGS`, `Limits.stricter(**changes)`, `DEFAULT_LIMITS`; `market_month`; `month_gate(month)`; `parse_member_path(name)`; `check_data_root(path)`; `HashingReader`; `safe_path`; `safe_target(root, sha, member_path)` | archive.py:95, :110-132, :168, :179, :200, :209, :245, :273, :383, :643, :662 | Read-only, symlink-safe, bounded, month-gated member loads. The suite uses stricter limits: DEFAULT allows 8 GiB decompressed per member (archive.py:120). `market_month` can return `None` (archive.py:200-206), and `month_gate(None)` raises `TypeError` (archive.py:211), so the suite refuses `None` first. |
| backtest.market_index | `HEAD_FILE`, `MARKETS_FILE`; `loads_strict(data)`; `market_sort_key(id)`; `load_manifest(root, sha)`; `archive_shas(root)`; head `files[]` entries with `status` and `complete_before_pt` | market_index.py:142-143, :215, :220, :225, :927, :720-724 (refused), :740-741 (indexed or unreadable) | Catalogue build and the strict line parse. Readability comes from the head's `files[]`, never from `evaluator_only_outcome`. |
| backtest.path_guard | `guard_path(path, where, prospective=False)`; `PathDenied`; `denied_sequence(path)` | path_guard.py:58, :37, :48 | Every suite path is checked: `guard_path(..., prospective=True)` for new files, and `denied_sequence` where a check without resolving is needed. |
| backtest.contract | `SEALED_HOLDOUT`, `INSPECTED_MONTHS`, `EXPOSED_MONTHS`, `NOT_PROSPECTIVE_DATES`; plus `research/experiments/backtest-p0-bsp-v1.json` `population.splits` | contract.py:154, :155, :159, :167 | Month roles come from the pinned files and are not hard-coded. Engineering (2015-05..2016-04) is visible; research (2023-01..2025-12) is hidden by default. The month-role JSON is read only through `pin.read_pinned()`, which checks its sha256 against the pin when it is read (Nuance's PR #2 review, item 8; 0a1c482). |

### 4.2 Test-only oracles (imported only under `tests/`)

| Interface | Citation | Test use |
|---|---|---|
| `paper.run_paper_replay(recording_paths, orders_path, params, out_dir, *, repo_root, snapshot_reader=None, key_type=None)`; `ORDER_FILE_KEYS` | paper.py:956, :61 | The parity oracle, on **small synthetic fixtures only** (capped at about 2,000 messages and 6 runners). It holds every snapshot in a list (paper.py:991-996); *measured (synthetic)* at about 1.98 GB RSS and 141 s for one 60k-message market. It is never run on real data. `repo_root` is never `~/betangel-research`, because `receipts.git_state` runs `git status --porcelain` there, which can rewrite `.git/index` (receipts.py:132-145; paper.py:956-957, :1053); a test asserts this. **Owed before 1b** (Nuance's PR #2 review, item 11): the parity test stubs `paper.git_state`, because under the test guard `git_state`'s `GuardRefusal` escapes its `except` (receipts.py:128-146). `runner_git_ok` is not widened for it, and the earlier plan of a temporary `git clone --local` of the deps clone is dropped. |
| `book.snapshots_from_recording(path, *, key_type)` | book.py:526-582 | The oracle for the yield tracker (section 6.2), including 503 windows. |
| `market_index._messages(stream, limits)` (private) | market_index.py:268-297 | Reader parity: one test imports it, so drift is caught on pin bumps. |
| `archive.ingest_archive(tar_path, data_root)`; `market_index.index_archive(root, sha)` | archive.py:765; market_index.py:870 | End-to-end data tests: a synthetic TAR is ingested and indexed into a temp root. Engine code never calls them (AST test). |

Oracles come only from the 25 closure modules (`paper`, `book`, `market_index` and `archive` are among them): any other upstream module is refused by the closure finder (section 3.5, item 4).

**No `risk` oracle (Nuance, Q-N1).** `risk` is not a test oracle. It is not pinned: Nuance found that a tampered copy of `risk.py` passed `pin.verify`. The suite's exposure code is checked instead against an independent exposure oracle written in the tests, as upstream's own tests do (tests/test_betfair_support_orders.py:724-760). The engine never imports risk (INTERNAL_ONLY, tests/test_betfair_boundaries.py:22).

### 4.3 Later phases (Air, Nuance-owned), never imported on the lab

| Interface | Citation | Later use |
|---|---|---|
| `killswitch.engage(paths, reason, *, clock)` | killswitch.py:57 | The real kill button on the Air (file-only KILL). The sweep stays in the repo CLI. |
| `esa.StreamClient.subscribe_markets`, `subscribe_orders` | esa.py:199, :211 | The delayed-stream view; order-stream position cache (P-5). |
| `recorder.StreamRecorder`, `verify_recording` | recorder.py:290, :830 | Air recordings for integration only. 2026 recordings never come to the lab. |
| `presence.order_echo_line(...)`, `TtyConfirmer` | presence.py:33, :80 | Stage-and-type: the suite shows the exact command and echo line, and Yu types them. |
| `backtest.replay.anchor_and_decision`, `replay_view`; `cohort.classify`; `accounting.win_gross_pence`, `commission_pence` | replay.py:122, :311; cohort.py:209; accounting.py:435, :443 | A later research overlay (P0 decision time, eligibility reasons) and a "same stake at BSP" debrief line. |

These are used only by the Air-side package in its separate repo (section 3.1).

### 4.4 Deliberately not used

- **`stream.messages`** (stream.py:15-32). It uses plain `json.loads`, which accepts NaN and Infinity tokens, and has no line or size bound and no hash check. market_index says it is not reused for these reasons (market_index.py:7-9). The suite has its own strict reader mirroring `_messages`.
- **`gateway.OrderGateway`** (gateway.py:351; `__init__` :354).
  - It imports the credential, arming, killswitch, presence, reconcile and risk modules (gateway.py:65-89).
  - It drives RiskGuard, which is INTERNAL_ONLY.
  - These are the deciding reasons (R-1).
  - A paper gateway also takes `.paper.lock` (gateway.py:612, :871). That clashes with Nuance's CLI paper commands only at the default per-Mac root (paths.py:81-82); with a root override, it would sit under the suite root.
  - Source `api` is paper-only anyway (gateway.py:859-863).
- **`risk.RiskGuard`** (risk.py:226).
  - It is INTERNAL_ONLY and imports capability.
  - In paper mode its R3 (risk.py:286-290) would also refuse a second click in a market while the first is still SUBMITTING during the 500 ms latency.
  - `JournalFolder.state()` defaults to `submitting_as_unknown=True` (journal.py:837).
  - The suite enforces its practice caps in suite code instead, and shows R3 only as a "live v1 shadow" flag.
- **`snapshots_from_recording` for interactive replay.** It snapshots every message: *measured (synthetic)* 49-207 s per market.
- **`path_guard.DENIED_COMPONENT_SEQUENCES`.** It is not a public interface (path_guard.py:25-27).

### 4.5 Private behaviour mirrored, and the contract test

The suite mirrors, and does not import, the following:

| Private behaviour | Citation |
|---|---|
| The strict member reader rules of `_messages`, including `complete_before_pt` | market_index.py:268-297, :14-20, :665-669 |
| The per-message yield rules of `snapshots_from_recording`, including the 503 window and catch-up | book.py:526-582 |
| `_simulate`'s order of operations: activate due orders against the previous snapshot, advance, activate at the last snapshot at pt (or at CLOSED), activate leftovers against the last snapshot, lapse at CLOSED, settle | paper.py:827-937 (leftovers :899-908) |
| `_journal_order`'s event shapes | paper.py:812-825 |
| `_SimClock` | paper.py:667-686 |
| `_lapse`'s result shape | paper.py:585-590 |
| The gateway's paper cancel sequence: the pre-submit records go to `PaperExchange.cancel`, and the post-submit CANCEL_PENDING records go to `classify_cancel_report` | gateway.py:1391-1485 (:1432-1435, :1461, :1478-1480) |
| `pnl.market_realized`'s commission rounding | pnl.py:79-82 |
| `MarketBookCache` being deep-copyable, for checkpoints | — |
| The `PaperExchange` state format | paper.py:58, :194-230 |

**The contract test.** Nuance agreed it, narrowed (Q-N1, PR #4 review): it does not exist yet, and Nuance found that seven injected breaks passed all tests. `tests/test_upstream_contract.py` lands on phase0/http. Every pin bump is gated on it, and it covers Phase 0's names first (`replay_market_time`, `parse_utc_ns`, `ticks.*`). In full, it fails loudly on a pin bump if any of these drift:

- `PARAM_KEYS`, `ORDER_FILE_KEYS`, `STATE_KEYS` (paper.py:58-61);
- `INTENT_PAYLOAD_KEYS` and `INTENT_SOURCES` (journal.py:95-97), and `KINDS` (journal.py:80);
- `BOOK_SNAPSHOT_KEYS` and `RUNNER_KEYS` (schemas.py:18-23);
- `PAPER_REFUSAL_CODES`, `PAPER_FAILED_CODES` and `TRANSITIONS["SUBMITTING"]` containing `REFUSED` (lifecycle.py:39-41, :72-74);
- the exact parameters, including which keyword arguments are required, of:
  - `validate_place`, `validate_cancel`;
  - `MarketBookCache.__init__`, `OrderJournal.__init__`;
  - `PaperExchange.place`, `.cancel` and `.advance`;
  - `OrderJournal.append`;
- `COMMISSION_SOURCES`;
- `FORBIDDEN_KEYS` still containing `session` and `token` (secret.py:114-116);
- that the indicative settlement equals `pnl.market_realized` for a market without removals (section 7.9);
- the deep-copy equality of a cache.

---

## 5. Data

### 5.1 Sources

| Source | Where | Use |
|---|---|---|
| Free PRO year, horse racing 2015-05..2016-04 (EX_ALL_OFFERS, TRD, TV, LTP, MARKET_DEF, SP_TRADED, SP_PROJECTED; sold as "tick-by-tick", but the files as observed record changes only, and changes may be conflated) | Downloaded by Yu to `incoming/data.tar`. Nuance ingested and indexed it into `~/betangel-data/historic-pro` on 2026-10-19 (`pro-ingest-01`; Q-N4, section 2.4). | **The only replay source.** Ladder replay and paper. The engineering year is already "seen", so using it spends no research months. |
| BASIC TAR (GB/IE WIN, 2015-05..2016-04 + 2023-01..2025-12, 1-minute LTP and definitions) | `~/betangel-data/historic` (ingested and indexed) | No UI mode. It is used only for counts-only checks run from the command line, in case the PRO ingest slips: a catalogue build and a reader smoke. Research months stay hidden. |
| Synthetic fixtures | Generated at test time into temp dirs by `tests/fixtures/gen.py` | All automated tests and every screenshot. |

Not on the lab, and never to be put there: the 2017 PRO samples (unless Yu fetches them), and any 2026 month, including the Air's delayed-stream recordings. Each 2026 month is refused by lab rule 4 and by `month_gate`.

### 5.2 Data roots and discovery

- The suite reads a configured list of indexed data roots. Each must pass `archive.check_data_root` (archive.py:273). It never reads `incoming/`.
- **No data root is read until Nuance's agreement of the suite root (Q-N3) is recorded** (Nuance, PR #1 review; Nuance's PR #1 re-review, finding 12). The flag `roots.STATE_ROOT_AGREED` is not that gate on its own: it is True on the unmerged branches, as lab-Claude's call, which Nuance accepts on conditions (section 3.7). The 1a reader also refuses while the flag is False, with a 1a test. Phase 0 reads no data root, and in every guard mode but engine the guard refuses reads in `~/betangel-data` (section 10, I-6; 0a3ed65). Nuance's agreement at 52a9edc adds condition (c): before 1a reads any data root, Nuance's identity checks (condition 2) and the marker and lock bound to the same home as the data (section 3.7).
- **Owed before Phase 1a (Nuance's Q-N3 condition 2).** The suite refuses a data root that equals, contains or lies inside the suite root, `~/betangel-data/lab-state` or `~/betangel-data/logs`, or that lies inside `incoming/`. It compares roots by file identity, not by path text.
  - Duplicate data roots are refused by identity too. Today `config.py` refuses only an exact repeat: Nuance found `HISTORIC-PRO` accepted beside `historic-pro` (Nuance's PR #2 review, Q-N3 additions). Nuance's own wrappers "refuse roots in suite.noindex, and duplicate roots, by identity".
- For every `manifests/<sha>.json` found by `market_index.archive_shas(root)` (market_index.py:927), it needs `index/<sha>/head-v1.json`, with these checks:
  - the head's `kind` is `betfair_historical_market_index_head`;
  - its `schema_version` is 1;
  - its `markets_sha256` equals the sha256 of `markets-v1.jsonl`;
  - its `manifest_sha256` equals what `load_manifest` returns.
  
  An archive without a valid index is listed as "not indexed yet" and is not opened.
- **One tier.** The MVP opens PRO members only. BASIC and PRO records of one market are never merged (market_index.py docstring), and there is no BASIC chart mode.

### 5.3 The catalogue (spoiler-free by construction)

- **Build.** One streaming pass over `markets-v1.jsonl`, line by line with `loads_strict`. The BASIC index is 568 MB, so it is never loaded whole. *Measured:* 4.3 s and 82 MB RSS for 52,561 records (real index, counts only).
- **Output.**
  - One SQLite row per (archive, plan, market), keyed by the sha256 of the head bytes, with `PRAGMA temp_store=MEMORY`.
  - It is built only by an explicit `bin/suite catalogue` command, never automatically on a head change, and never while the run marker exists.
- **Fields read:**
  - `provenance`: archive_sha256, member_path, member_sha256, file_type, plan, path_month, path_date. The member's size and `decompressed_bytes` come from the manifest.
  - `decision_time`: first-published marketTime, the definition timelines up to the cutoff (venue, eventName, name, countryCode, marketType, numberOfWinners as declared, bspMarket), runners (id, name, sortPriority), and removals before the cutoff (the "non-runner declared" badge).
  - The head's `files[]` entry for the member: `status` and `complete_before_pt` (market_index.py:720-724, :740-741).
  - The role and the gate (below).
- **Roles and gates.**
  - Each market's role comes from `market_month(first-published marketTime)` and the pinned contract splits.
  - `month_gate` is checked on both `path_month` and `market_month(marketTime)`.
  - A `None` month is refused as `month_unknown` before `month_gate` is called (archive.py:200-206, :211).
  - A market whose month lies in no split is hidden, and a visible count is shown. Example: 8 members of the PRO TAR have path month 2016-May, which passes `month_gate` but lies in no split.
- **Never read:**
  - `evaluator_only_outcome`;
  - `coverage`, which is outcome-correlated;
  - `provenance.other_sources`, whose `agrees` field compares outcome parts and so is outcome-derived (market_index.py docstring);
  - `view_ends.reason`, which can reveal an early close.
  
  A test plants outcome values in a synthetic record and asserts they never reach SQLite, a frame or the browser before CLOSED.
- **Records with no view** (no marketTime before the cutoff) are counted and not listed.
- **Visible by default:** the engineering year.
  - **Research months.** While `research_months_ruling` is null, research-month records are **not written** to the catalogue at all; only their counts are stored. Enabling them needs a ruling id from Yu with Nuance and Astra, and a reviewed PR that lists the id in `config.ACCEPTED_RULINGS`: in Nuance's words, `research_months_ruling` is "only null until Q-Y7" (PR #1 review, item 11; section 3.8). The id is recorded in the ledger, logged at startup, and shown in the picker. A research month in which a market is opened becomes inspected (contract.py:39; Nuance's answer to Q-N11).
  - 2017-04 is inspected and 2026 is refused.

### 5.4 Opening a member

1. **Path and month checks.** `path = archive.safe_target(root, archive_sha, member_path)`, then `path_guard.guard_path(path, "member")`. A `None` month is refused as `month_unknown`. Then `month_gate(path_month)` and `month_gate(market_month(marketTime))` are checked again. Any refusal stops the open.
2. **Limits.** Read the compressed file into memory once, bounded by the suite's `Limits.stricter(max_member_bytes=32 MiB, max_member_decompressed_bytes=256 MiB, max_line_bytes=1 MiB)`.
   - *Measured (real, aggregates):* the largest real member is 7.8 MB compressed and 74 MB decompressed, and its longest line is 57 KB.
   - The limits are revisited at the first ingest.
   - A refusal by a suite-only limit has its own code, `suite_limit_exceeded`, so it is never confused with the index's own `unreadable`.
3. **Integrity.** Compute the sha256 and size of **those bytes** and compare them with the manifest member. Decompress from the same bytes, so there is no gap between checking and using them. On a mismatch, refuse with `member_integrity_failed`, with no partial replay. The total decompressed size must also equal the manifest's `decompressed_bytes`, which `load_manifest` requires to be an int (market_index.py:260).
4. **Decompression.** Decompress with `bz2.BZ2Decompressor` using `max_length` chunks into one `bytes` blob. Keep line offsets as `array('Q')` and pts as `array('q')`. The blob is held in memory only. *Measured (real, aggregates):* median 8.1 MB decompressed, maximum 74 MB.
5. **The strict reader.** It mirrors `_messages`: blank lines skipped, only op `mcm`, an integer pt that never decreases, no `segmentType`, `max_line_bytes` per line and the member budget, parsed with `loads_strict`.
   - A violation stops the replay there, with a visible "file ends early" marker.
   - Replay only messages with pt < `complete_before_pt` (market_index.py:14-20, :665-669):
     - `complete_before_pt` is the failing message's pt if it was read;
     - otherwise it is the last applied pt (the line was not JSON, was NaN, was too long, or was cut mid-line), and that whole last batch is excluded too.
   - The head's `files[].status == "unreadable"` with `complete_before_pt` says the same thing in advance, and the picker shows it.

### 5.5 Licensed-data rules

- Data roots are read-only to the suite. A test hashes a synthetic data tree before and after a full session.
- **Derivatives.** Every derivative goes under the suite root (0700): the catalogue, journals, `commands.jsonl`, session reports, problem reports, the ledger, exports, logs, private tracebacks and temp files. Nothing decompressed is written anywhere. SQLite temp files are kept in memory, and `TMPDIR` and `SQLITE_TMPDIR` point inside the suite root (section 3.6).
- **The browser.**
  - API responses are `Cache-Control: no-store`, `localStorage` holds UI preferences only, the session token lives in JS memory only, and the CSP blocks external requests.
  - **Use a Safari Private window** on both machines (Q-Y11: Yu's answer of 2026-10-17, over the alternative of a dedicated profile with no Betfair login, no extensions and no iCloud sync). In a normal window, Safari History, iCloud History and iCloud Tabs would sync the URL and title. Safari may also keep page thumbnails (*inference*).
  - `document.title` is static. The bootstrap code is single-use and valid for 120 s, so a copy left in history is dead once the page has redeemed it or 120 s have passed, whichever comes first (section 9.2).
- **OS-level copies.**
  - The suite root's `.noindex` suffix keeps Spotlight out of it. Yu is asked to add `~/betangel-data` to Spotlight Privacy (Q-Y15).
  - Mac Analytics auto-submit is on, so a native crash report from python3.13 or Safari WebContent would be sent to Apple. That is put to Yu as a privacy decision (Q-Y14).
  - Data is kept out of exception text (section 9.2, item 9).
- **No upload, sync or share features.** Exports are 0600 CSV files under `exports/`, headed "Personal use only; Betfair Historical Data licence".
- **Viewed-markets ledger.**
  - `ledger/viewed-markets.jsonl` records, for every market opened, the month-level fields of Nuance's answer to Q-N11: a keyed hash of the market (never its id in the clear), plan, month, role, opened_by, furthest phase, attempts and ruling id.
  - **Agents never read it.** `bin/suite ledger-summary` prints counts only, by month, role, plan and attempt.
  - Nuance's trial ledger holds no market ids (trial_ledger.py:96), so there is no hash matching. Reconciliation is at month level, by the counts `ledger-summary` prints (Nuance's answer to Q-N11).
  - Historical: draft 0.2's list (market id, archive sha, wall time, furthest replayed pt, whether CLOSED was reached, the session ids) held the market id in the clear. Round 5 replaces it with Nuance's fields (Nuance's PR #1 re-review, finding 11).
- **Agents never see rows** (section 3.9). `bin/suite selfcheck`, `catalogue`, `diagnose` and `ledger-summary` print codes, counts, salted hashes and timings only.

### 5.6 What never goes in git

- **File types:** `*.bz2`, `*.tar`, `*.sqlite*`, `*.jsonl`, exports, runs, screenshots outside `docs/synthetic/`, and any file over 512 KiB. There is one exception, this document, approved by Yu on 2026-10-19 (section 2.2.1; it answers Astra's and Nuance's PR #1 reviews): it may grow up to 2 MiB, it is still content-scanned whole (`SIZE_ALLOWLIST`; Astra's PR #1 review, item 12), and every change to it is reviewed by Nuance and Astra. Every other file stays under 512 KiB. Enforced by `.gitignore`, `tools/hygiene_scan.py` and four git hooks: `tools/pre-commit` and `tools/pre-merge-commit` (the staged tree), `tools/commit-msg` (the message) and `tools/pre-push` (every commit and annotated tag a push publishes, messages included). **On the lab only `pre-commit` is live today:** the hook links live in the main clone, whose checkout has only `tools/pre-commit`, so the other three links dangle and git skips them (AGENTS.md, "Repository hygiene"). Until they are live, no hook scans a commit message or a push, and the manual scans before a push are conduct (Nuance's PR #2 re-review, F9). **Phase 1a entry gate** (Nuance's F9; lab-Claude's decision to adopt it): before Phase 1a starts, the scanner on every live branch accepts `--message` and `--push`, the two `event_id` findings in the history of PR #3 (proposal/001-agent-seat), which a push through the hook would block, are dealt with, all four links resolve, and a synthetic `commit-msg` block and a push blocked by a local bare remote are shown on the lab. The scanner also catches binary data anywhere in a file, data hidden in text (`encoded_blob`), and paths a clean filter rewrites (`filter_attribute`) (Nuance's PR #2 review, items 5, 19, 20 and 21; 50fe1b7, ebd1038, 6149d94, 526efcb, 268d02d). Lab-Claude's round-4 review and its recheck added:
  - every git call of the scanner has replace refs and grafts off (`GIT_NO_REPLACE_OBJECTS=1`, `GIT_GRAFT_FILE=/dev/null`), so it reads the blobs and parents a commit records and a push sends, never a stand-in (783125d);
  - `--push` refuses more than 1 MiB of pre-push lines (`push_input`) instead of cutting them short, which dropped every later ref (b4c2656);
  - **what `--push` leaves out** (Nuance's PR #2 re-review, F3; 77271cd): only commits reachable from the old values that the remote reports in that push's own lines, when this clone holds them. It never trusts this clone's tracking refs (`refs/remotes/<remote>/*`), which can be stale until `git fetch --prune`: in Nuance's probe a commit deleted on the remote, with a stale tracking ref still naming it, went back unscanned under a later clean commit. So a push that creates a ref scans all the history behind it: `--range` over 148 commits of this branch (541 items) took about 15.5 s in round 5, and Nuance measured about 14 s for 129 commits. Lab-Claude accepts that cost (lab-Claude's answer, round 5 close). A manual `--range origin/<branch>..HEAD` still trusts `origin/<branch>`, so it needs `git fetch --prune` first (AGENTS.md);
  - **whole objects** (Astra's re-review of PR #2, new finding 2; fbd60fa): `--push` reads each commit and annotated tag object whole, and `--range` each commit object, and both refuse one over 1 MiB by its size, before any of it is parsed (`object_oversize`, exit 2). `--range` reads no tag object: rev-list peels a tag to its commit, so an annotated tag's message is scanned only by `--push`, and AGENTS.md's manual steps feed `--push` a tag's line before it is pushed (lab-Claude's round-5 review). They used to keep a 1 MiB prefix, so an author or tagger line that filled it left no blank line in what was kept, and the message read as empty and passed;
  - **`--message`'s read boundary** (Astra's re-review of PR #2, new finding 3; 35345ba): it opens its file a component at a time with `O_NOFOLLOW`, checking each name and each link target and never following a link (at most 40 links); the last component must be a regular file. So `alias/MSG` and `down/../MSG`, with a link into a data root, are refused, and so is a `/.vol` spelling (`message_unreadable`). Before, only the normalised text and the last component were checked;
  - **encodings decoded** (`encoded_blob`; 7085b08): base64 (standard and URL-safe); hex bare, split by one or two spaces or colons, right after `\x` (a PostgreSQL bytea literal), as `0x` lists, and in xxd, `hexdump -C`, `od -An -tx1` and `od`'s default octal output; `\xNN` escapes; string literals of four or more octal escapes (three-digit, or C's shorter `\N` and `\NN`; C and shell `$'...'` strings), and the short last line of such a run with one (Nuance's PR #2 re-review, F7; 58e8426); decimal byte lists (a sorted list, such as a price ladder, is not data); and GIT binary patches. Runs join across lines, also when each line starts with the same comment or list marker, and a decoded run of text is searched once more (base64 of base64);
  - **known gaps, not decoded:** base32, base85 and Ascii85 outside a GIT binary patch, uuencode, quoted-printable, UTF-7, JSON `\u` escapes, base64 split into pieces under 16 characters (groups of 8, or a list whose first piece is that short), lists split by commas, `\xNN` and octal escapes outside a quoted literal (`printf`'s unquoted argument), and literals of three or fewer octal escapes and no `\xNN` each (Nuance's PR #2 re-review, F7, offered listing them; 9389c7d);
  - **lists of hashes** (2ae7640, 287264a, b656145, fab0b92, 7126190, bfd2f6a): a hex run of two or more lines, each one whole token of exactly 40 or 64 digits (a list of commit or file hashes, bare, quoted or after a marker), is not counted as binary data while the lists in its file or message hold at most 64 lines in all, each line counted once, and while it is not in a decoded run. It is still flagged if an archive or SQLite magic, an image or document signature (PNG, JPEG, GIF, WebP, ISO media, TIFF, PDF) or a zlib stream starts at any of its lines, or if it holds text another rule flags, read with each NUL as a line end and other bytes that are not UTF-8 replaced, and, if it holds a NUL, read again with the NULs removed (UTF-16 text; fab0b92). Past 64 lines in all, every list in that file or message is binary data again, as before 2ae7640, and so is every list in a decoded run read as text, whatever the count; such a list that holds a NUL or is not UTF-8 is flagged at any length, not only from 96 bytes (bfd2f6a). Either way, a magic, an image or document signature or a zlib stream still counts at the start of any of its lines (145fa22; the final recheck of bfd2f6a, which had tested such a list from its first byte only, so an ASCII PDF on its second line passed). b656145 counted each run alone, so runs of 64 lines split by a blank line passed however many there were; counting per file or message is lab-Claude's decision (7126190; the finishing review's recheck). 7126190 still gave each decoded run a count of its own, so base64 runs that each decoded to a list of 64 lines passed however many there were, and past the count lists of two to four lines, under 96 bytes, still passed when split by blank lines (bfd2f6a; the recheck of 7126190). So the exemption carries at most 64 lines, about 2 KiB, in one file or message. A line with one hash and words after it is not a list and is not counted. Before 287264a and b656145 only the run's first byte was tested and only valid UTF-8 was read as text, so data after one real hash line, text with one NUL or 0xFF byte, and images and PDFs passed (round-4 finishing review). This also clears a false positive older than 7085b08: a bare list of three or more sha256 lines was flagged as binary from `encoded_blob`'s first version (6149d94) on;
  - **short runs** (53904f8): any other decoded run of 16 to 95 bytes that holds a NUL or bytes that are not UTF-8, too short to count as binary data, is read as text in the same way. Before 53904f8 it got neither test, so one record ending in a NUL, or after a 0xFF byte, passed (the finishing review's recheck; as old as 6149d94);
  - **known gaps, not flagged:** in lists of hashes, binary data with no signature above and no zlib stream at a line's start (raw deflate, a compressed file without its header, encrypted bytes, or a signature that starts mid-line), up to 64 lines, about 2 KiB, in one file or message, outside a decoded run (2ae7640, b656145, 7126190, bfd2f6a); and binary data with no signature in runs of under 96 bytes each, however many: a blank or other line every few lines, a change of marker, or text before or after the token on each line (a numbered list, trailing words), so that each run is too short for the binary test. One hash line alone between blank lines is such a run. This gap has no bound, and it is older than 2ae7640 (the recheck of 7126190 named it in general);
  - **known false positives** (failing closed): lists of md5, sha224, sha384, sha512 or blake2b sums, lists of lines that hold two or more hashes split by spaces (`git log --format='%H %P'`), lists of hashes that hold more than 64 lines in all in one file or message, however they are split into lists of two or more lines (7126190; at any length since bfd2f6a), and a list of two or more hashes in a decoded run, such as base64 of a text that lists commits (bfd2f6a). A word after each hash on its line avoids them. Also a Latin-1 (or other non-UTF-8) string literal of four or more octal escapes and 96 or more bytes, which is binary data to the scanner, as `\xNN`-escaped text already was (58e8426);
  - **linear time** (805356c, 1be5dc1): no pattern grew worse than linear in an audit of 660 line shapes, once possessive quantifiers and an atomic group removed the backtracking found. `_SECRET_LOOSE` took 212 s on one 120 KB snake_case line, and six more patterns were quadratic or cubic. The audit missed string literals, which were tried again from every quote: a line holding `\x` and an unclosed literal full of escaped quotes took 16 minutes for 512 KB (round-4 finishing review). They are now read in one pass (1be5dc1). The regression test scans 200 KB lines of 29 shapes, one per file, each within 10 s; round 5 added the octal and NFKC shapes (58e8426, 1e39931). Round 5's wider lead cells (1e39931) broke this for rows of cells split by runs of tabs, a tab being both a separator and whitespace: three such cells took about 5 s to fail to match on one 400-character row, which `MAX_TABLE_LINE` bounds, so a file of such rows took minutes (lab-Claude's round-5 review). The separator is now an atomic group, and the test also scans a file of 60 such rows (1e91dd9). The worst line is U+FDFA, which NFKC makes 18 characters: its 200 KB line takes about 1 s, and a 2 MiB DESIGN.md of it about 11 s (0.5 s before NFKC), still linear (lab-Claude's measurements, round 5, after 99ed70d). The fix uses possessive quantifiers and an atomic group, so the scanner needs Python 3.11 or later: the hooks run it with 3.13, and the tests run on 3.11 and 3.13. `known_token` now reads a JWT with its own pattern, so a JWT that overlaps another provider token is found as well;
  - `runner_table` reads box-drawing tables (SQLite's `.mode box`, DuckDB), HTML cells, LaTeX's `&` and a fullwidth bar, accented names, and names in capitals when the row holds only prices (00067cd); `secret_value` reads unquoted values after a colon, after " is ", and after a bare space for `ssoid`, session token, app key and api key (c5a5576);
  - **lines read in NFKC form** (Nuance's PR #2 re-review, F8; 1e39931): every line the rules read, and the path text the id rules read, is read twice: as written, with format characters dropped as before, and with format characters and default-ignorable code points dropped, in NFKC form. A finding in either counts (99ed70d). 1e39931 read the NFKC form alone, which hid findings where NFKC joined a character onto a token: a superscript, an ordinal, a ligature, U+2122 or U+2116, a Roman numeral, a fraction or a fullwidth letter beside a base64 or hex run, a provider token, an id or a member path (lab-Claude's round-5 review). So no-break, figure, narrow and ideographic spaces, fullwidth digits and letters, and U+034F or U+FE0F inside names and ids are caught. A runner table may be led by up to three number, time or date cells: a time, an ISO or d/m/y date with an optional time and zone, or an id of 4 to 13 digits;
  - **known gaps of the runner and id rules:** names in non-Latin scripts or in look-alike letters (Cyrillic, Greek); digits of other scripts (Arabic-Indic, Devanagari), which NFKC does not map to ASCII (mapping every decimal digit, Unicode category Nd, to ASCII is a later option, not built: lab-Claude's answer, round 5 close); other lead cells (12-hour times such as "1:30 PM", month names, more than three cells); and short or name-only tables (below).
- **Fixtures:**
  - synthetic only, generated at test time, never committed as binaries;
  - reserved ids: markets `1.999xxxxxx`, events `99xxxxxx`, selections `9xxxxxxx`;
  - venue "Synthetic Park" and runners "Synthetic 1..n".
  
  In synthetic mode the engine refuses non-synthetic ids and every configured real data root.
- **The scanner is bounded pattern detection, not proof** (Astra's PR #1 review, item 6). Outside that namespace it flags, among its other rules, market-id shapes (`1.1` or `1.2` and 8-9 digits) and tables of three or more rows that pair a capitalised name with price columns. It does not catch a short or name-only table, the shapes listed as known gaps above, or licensed facts in prose, and it allows images under `docs/synthetic/` by their place, without proving where they came from. So "nothing licensed in git" (rule 4) stays a conduct rule: the author and the reviewers of each PR check the provenance of what it adds, and a clean scan is never described as proof that content is synthetic or unlicensed.
- **Writing:** no real-market screenshots, prices, names or ids in PRs, issues, Collab or the mailbox. PR descriptions, review replies and other outbound text are scanned with `tools/hygiene_scan.py` before they are posted (Nuance, PR #1 review).

---

## 6. Replay engine

### 6.1 Clock

- **Time axis.** Time is Betfair publisher time (`pt`, integer ms). Wall time (`time.monotonic_ns`) is used only for pacing:
  - `target = V + (wall_now - wall_anchor) * speed`;
  - speeds 0.25x, 0.5x, 1x, 2x, 5x, 10x, 30x and 60x, pause, step to the next pt batch, and step 1 s while paused.
- **Atomic batches.** The clock applies every whole pt batch with `pt <= target` and never stops inside one, matching "the last snapshot at that pt" (paper.py:896-902).
- **Jump marks** are relative to the first-published marketTime: T-30m, T-10m, T-5m, T-2m, T-1m and the scheduled off. The observed in-play flip is marked separately, with a tooltip that races can start early.
- **Options.** Auto-slow to 1x at T-3 min. Auto-pause at the scheduled off and at the in-play flip.
- **Pause unless watched.** The clock runs only while a controller is watching (section 8.6). Otherwise it pauses.
- **Effective speed.** In exact mode, a CPU budget (40 ms per tick) can make V lag. The banner then shows the effective speed, for example "speed 10x, effective 6.3x (exact paper fills)". Messages are never skipped.

### 6.2 Book reconstruction and the yield tracker

- **Cache.** `MarketBookCache(key_type="historical", app_key_slot=None, source="recording")`; all three keyword arguments are required. `apply` costs about 7-10 µs per message (*measured, synthetic*). Parse plus apply costs 13-20 µs per message on real PRO members (*measured, real*).
- **Yield tracker.** `replay/tracker.py` mirrors the rules of `snapshots_from_recording` (book.py:556-576) for the focused market M, without taking snapshots. After each applied message it records whether the oracle would have yielded M, and with which stamp:
  1. **Entering a 503 window** (the message has a non-null status and the previous one did not): M yields, stamped at this message's pt, unusable (`stream_unreliable`), and goes into the window's pending set.
  2. **Inside the window:** M yields, stamped and unusable, whenever the message changes M.
  3. **The first healthy message after a window:** if M was pending and this message does not change M, M yields a catch-up stamped at this pt and usable. If the message changes M, M yields unstamped at its own pt.
  4. **Otherwise:** M yields, unstamped, whenever the message changes M.
- **Materialising a snapshot.** Between yields, M's state does not change, so `materialise(M)` is simply `cache.snapshot(M, unreliable_ok=<last yield unusable>, stamp=<last yield's stamp or None>)`. That is exactly the snapshot the oracle's timeline holds for M at that moment. Display frames, click validation and activation books all use it.
- **Test.** In "emit every yield" mode, the tracker's sequence for M equals `[s for s in snapshots_from_recording(path) if s["market_id"] == M]` on synthetic fixtures with suspensions, images, removals, version changes and 503 windows.

### 6.3 Display mode and exact mode

| Mode | When | Work per message |
|---|---|---|
| Display | No paper order pending or open in M | `apply` plus tracker bookkeeping. A snapshot is taken only at frame ticks. |
| Exact | Any order in M is pending (SUBMITTING before activation) or EXECUTABLE | At **every yield** of M: materialise the snapshot, activate due orders, then call `PaperExchange.advance(prev, cur)`, exactly in `_simulate`'s order (section 7.4). |

- **Cost of exact mode.** *Measured (real, aggregates):*
  - `snapshot()` costs 0.46-4.35 ms and `advance()` with no orders 0.95-8.14 ms, so a step costs 1.4-12.5 ms, about 5 ms at the median;
  - this was over 5-44 runners and 721-6,166 book entries, and both calls validate full books (schemas.py:164-219; paper.py:558-570).
- **Sustainable speed near the off.** Real markets publish about 9 messages a second in the last 10 minutes (median), and 14-25 in the busiest second. Exact mode sustains about:
  - **20x** on a median 16-runner field;
  - **13x** at 22 runners;
  - **8x** at 44 runners;
  - **3x** during the busiest second before the off.
  
  Beyond that, the clock lags and is labelled.
- **Leaving exact mode.** After every order in M is final (lapsed at the off, fully matched, cancelled, or withdrawn before activation), the engine drops back to display mode. In-play replay is therefore cheap.
- **Any coarser paper cadence** (sampled stepping) is **not** in the MVP. It becomes a later proposal (U-6), and it needs a proof first:
  - per-step flooring (`consumed = floor(delta*100/divisor)`, paper.py:543) means fewer, larger steps can fill more;
  - every status-bearing (503) message and every definition change would have to be a forced step point, because a 503 window raises the traded high-water mark without filling (paper.py:470-482, :552-553).

### 6.4 Seek, checkpoints and forward-only sessions

- **What a checkpoint holds.** A deep copy of the cache, the yield tracker, the SP and definition tap, and the traded high-water tracker *as of that position*.
- **Checkpoint schedule.**
  - Files start 25-53 h before the off, and 53-91% of their messages come before T-30m (*measured, real*). So the pre-T-30m prefix is applied without checkpoints, except one at T-30m.
  - From T-30m on, there is a checkpoint every 10-15 s of pt or every 500 messages, whichever comes first, plus one at every jump mark.
  - *Measured (real):* a deepcopy costs 0.4-2.9 ms. Under the old every-1,000-messages schedule, all checkpoints for one market came to 2.7 MB (median) to 44 MB (max). The new schedule holds far fewer.
- **Forward seek with no orders:** apply only. *Measured (synthetic)* at 54k messages in 0.57 s.
- **Forward seek with orders open or pending:** either "fast-forward in exact mode" (progress shown, CPU-bound) or "cancel my orders first". It is never skipped.
- **Backward seek** restores the nearest checkpoint and re-applies forward. *Estimate:* under 50 ms after T-30m. A seek to before T-30m re-parses from the start: up to about 4 s for the largest member, with a progress bar.
- **Forward-only after the first paper order.** Once a session has an order, backward seek is refused.
  - "Void and rewind" (a typed confirmation) first withdraws every pending order, with its own reason, and cancels every EXECUTABLE one (section 7.6; in both modes, since void never activates a pending order). It then closes the session as `voided_rewound`. The journal gets a `note`, the session is excluded from practice totals, and a new attempt starts with a new journal.
  - This prevents hindsight trading. It also keeps the journal clock monotonic: the fold flags a regression beyond 5 s (journal.py:93, :877).
  - The attempt counter for each market is shown in the picker and in the debrief.

### 6.5 Frames

- **When built.** Only when something changed and at least 1/`frame_hz` has passed (default 10 Hz). In exact mode the latest yield's snapshot is reused.
- **Contents:**
  - clock: V, speed, effective speed, paused (and why), ms to the scheduled off, off detected;
  - market: status, in-play, version, bet delay, `invalid_reason`, last-change age;
  - every runner: status, LTP, total matched, best 3 back and lay with sizes, WOM, back and lay book %, and projected SP from the tap;
  - ladders only for the subscribed runners: a ±40-tick window of back, lay and traded size, our orders by price with queue-ahead, and what paper has already taken at each level (`export_state()["taken"]`).
- **Traded volume** is shown on the repo's PRO basis (÷2; paper.py:1016) and labelled as such.
- **Encoding.** One JSON object per frame, 5-20 KB (*estimate*), so 200 KB/s or less at 10 Hz. Delivered as NDJSON over a streaming `fetch()` (section 8.5).

### 6.6 SP and definition tap (display only)

- **What it is.** A suite-side parser over the same message dicts (R-5), needed because RUNNER_KEYS has no SP fields. It reads:
  - `rc.spn` and `rc.spf` (projected near and far);
  - `rc.spb` and `rc.spl`;
  - `md.runners[].{name, sortPriority, status, adjustmentFactor, removalDate, bsp}`;
  - `md.{status, inPlay, version, marketTime, suspendTime, betDelay, bspMarket}`.
- **Values.** It keeps the latest values at V. Quoted `"NaN"` and `"Infinity"` SP strings count as missing. On Nuance's terms (PR #1 review; Nuance's answer to Q-N9):
  - it resets at every image (`img`);
  - `spb` and `spl` are deltas, applied as `book.py` applies them and cleared while the market is not OPEN (book.py:239-255);
  - a `bsp` is shown only within [1.01, 1000].
- **Isolation.** It is labelled "SP: suite display parser, not in the betangel-research schema", and it is never passed to `PaperExchange` or `validate`.
- **But SP content still reaches paper through `book.py`.** A non-finite size in `spb`/`spl` marks the snapshot `non_finite_size`, and a non-finite `spb`/`spl` price poisons the runner (section 2.4). Either one makes V9 refuse and blocks paper fills until the next image. The frame shows the `invalid_reason`, and the debrief counts these refusals.
- **First PRO measurement.** At the first PRO ingest, count the markets and snapshots whose `non_finite_size` comes from SP fields (counts only), and feed the result into U-2. The ingest ran on 2026-10-19 (section 2.4), but the stock audit has no such count: it needs a small reviewed counter, a follow-up of Nuance's (Nuance's mailbox notes of 2026-10-18 and 2026-10-19), so these counts are still owed.
- **No spoilers.** The final `bsp` and runner WINNER/LOSER appear only when the replay reaches the definition carrying them. A spoiler test asserts that no result or BSP value is serialised to any frame before its pt.
- **Upstream proposal.** U-2 would add SP fields to the snapshot schema, and settle how SP non-finites should affect validity, so the tap can be removed.

### 6.7 Performance and memory budget

*Measured (real, aggregates)* unless marked synthetic: 12,208 PRO market files from the PRO TAR, with rates near the off from 40 random members.

| Item | Measured | Budget or target |
|---|---|---|
| Member size | compressed: p10 518 KB, median 764 KB, p99 1.48 MB, max 7.8 MB. Decompressed: median 8.1 MB, max 74 MB | suite limits 32 / 256 MiB (section 5.4) |
| Messages per member | median 30k, p99 79k, max 261k; files span 25-53 h | — |
| Rate near the off | 3,309-5,922 messages in the last 10 min (median 5,410, about 9 a second); busiest second 14-25 | — |
| Open (read, hash, decompress, parse, apply, checkpoints) | parse plus apply 13-20 µs a message. The median member costs about 0.75 s of CPU. The largest costs about 6.3 s: bz2 0.9, parse 1.4, apply 3.1, checkpoints 1.0. | **p99 ≤ 2 s, max ≤ 8 s**, with a progress bar |
| Exact step (snapshot + advance) | 1.4-12.5 ms, about 5 ms at the median | the clock lags beyond 40 ms per tick |
| Exact-mode sustained speed near the off | about 20x (16 runners), 13x (22), 8x (44); about 3x in the busiest second | labelled lag beyond that |
| Checkpoint deepcopy | 0.4-2.9 ms each | the section 6.4 schedule |
| Seek | about 25 ms after T-30m (estimate); up to about 4 s before T-30m | ≤ 50 ms after T-30m |
| `snapshots_from_recording`, every message (synthetic) | 49-207 s | never interactive |
| `run_paper_replay`, one 60k-message market (synthetic) | 141 s, 1.98 GB RSS | tests on fixtures of about 2,000 messages only |
| Catalogue from the real BASIC index | 4.3 s, 82 MB RSS (counts only) | ≤ 30 s, ≤ 300 MB |
| Engine memory | the 600 MB target holds | below |

**Memory.**

- Engine target 600 MB RSS, soft cap 1 GB, hard cap 1.5 GB.
  - Above the soft cap: no new opens or prefetch.
  - Above the hard cap: evict the prefetch and older checkpoints, and pause.
- RSS is kept within budget by counting what the engine holds (blobs, offsets, checkpoints) and is checked through `resource.getrusage` in tests.
- An LRU of 2 markets: the focused race and the prefetched next race.
- One Safari tab adds about 200-300 MB (*measured* about 220 MB for WebContent).

**CPU courtesy.** `os.nice(10)` always. Prefetch runs only in display mode or while paused (section 3.2). No engine runs while the run marker exists (section 6.8).

### 6.8 No engine during Nuance's runs

Nuance has answered: during a real run, "a suite elsewhere is harmless but slows the run; please avoid it" (mailbox 08:57Z, A5). So the rule is **no engine during runs**, not a reduced quiet mode.

- **The marker.**
  - The marker is `~/.local/state/lab-runs/ACTIVE`, written by Nuance's run wrapper, outside `~/betangel-data` and not under Nuance's `~/betangel-data/lab-state`.
  - Only Nuance's run wrapper creates and removes it. Lab-Claude never does.
  - **Its status (Q-N3).** Nuance agreed it in Nuance's PR #4 review. Nuance's PR #2 review makes that agreement conditional again: "agree the root half after 1, the marker half after 6", where 1 and 6 are Nuance's PR #2 findings (roots that resolve into `~/betangel-data`, and the marker protocol). Item 6's terms are in "The real-data lock" and "Nuance's side" below.
  - **Agreed as built, pending two findings** (Nuance's answer to lab-Claude's question 8 of 2026-10-17, PR #2 re-review): "I agree the root half (item 1) and the marker half (item 6) as built at 823c194, pending F4/F5." F4 and F5 are that re-review's findings on a freshly loaded `_posixsubprocess` and on a state root linked to `~/.local/state`, which reopened `lab-runs/`. Both are fixed on this branch: F4 in ff35218 and F5 in c3b0c61 (sections 10 and 3.7). c3b0c61 changes placement, so by Nuance's second condition below the re-check is open again, at the merge-candidate SHA (lab-Claude's reading). Nuance's conditions: the agreement is recorded at the merge-candidate SHA; "any later change to placement/runmarker/root-lock protection reopens the re-check"; and until then no engine command runs on the lab with the real HOME.
  - **Agreed as built at 52a9edc** (Nuance's review of PR #5 at 52a9edc): "Q-N3: I agree both halves, root and marker, as built at 52a9edc." Nuance's conditions (a) to (d) are in section 3.7. Under (a), a later fix that touches the Q-N3 file set reopens only its own diff, and Nuance confirms the agreement at the merge SHA in one line. Nuance probed with Nuance's real wrapper functions in scratch HOMEs: a suite holder leaves once the marker appears, every command except `stop` refuses under the marker, and a state root linked onto `lab-runs` is refused.
  - It is checked first by `_launch.py`, before anything is created under `~/betangel-data`.
  - **Scope, by rule rather than by list** (Nuance, PR #1 review, item 5): every upstream step on real roots. That is real backtest runs, the PRO ingest and index, and the runbook's lab steps, its L2 and L3, certify-engine and reconcile-trials included. The runbook's section 10.1 runs bare commands today; Nuance adds a marker step to each of its blocks (Nuance's amendment to Q-N3). Upstream allows one tool per data root at a time (docs/backtest-plan.md:213).
- **At start.** The engine, every real-data command (`catalogue`, `selfcheck`, `diagnose`, `ledger-summary`) and `bin/suite test` refuse to start while the marker exists. An unreadable marker, or an unreadable marker directory, counts as present.
  - `ledger-summary` is lab-Claude's addition to Nuance's list: it reads only the suite root, but its output is a real-data derivative (section 8.6), and its `TMPDIR` lies under the suite root (section 3.6).
  - `bin/suite test` refuses in both tiers and on both interpreters (`test` and `test --py311`), with the same codes, `run_marker_present` and `run_marker_unreadable`. Tests were first exempt. Nuance answered Q-N14 "no": "Please make the fast tier refuse while the marker exists too; stop stays exempt" (mailbox, 2026-10-16 13:41Z; PR #4 review, item 14).
  - A run already going checks the marker again after every test (`cli.marker_stop_result`). If the marker is present or cannot be checked, the run starts no further test and ends with the same code and exit 2. The test then running is not stopped; it finishes first, with anything it started.
  - Item 14 also asks to "check it before each engine launch". Tests on this branch start no engine, so that check is owed with `engine.py` on phase0/http.
  - Only `stop` skips the check, because it only reduces activity (section 3.9, rule 6). `vendor` refuses too. It writes the deps clone under `~/.local/share` and, with `--bump`, `pin/`, and it clones the whole of `~/betangel-research`. It was first exempt by lab-Claude's own choice; Nuance's PR #1 review answered Q-N14 "test and vendor refuse under the marker; stop stays exempt".
  - Nuance's PR #2 review answers Q-N14 the same way: "No. Drop `test` from NO_RUN_MARKER_CHECK; from #4 the fast tier starts ~20 temp-HOME engines blind to the real marker. Check it per module in _run_workers.assign()." `test` is not exempt on this branch. The per-module check belongs to the parallel test runner on phase0/viewing; on this branch a run checks after every test.
- **The real-data lock** (Nuance, PR #1 review, item 5, and PR #2 review, item 6, which Nuance merges with it). The headless commands check the marker only at start and would hold nothing Nuance's wrapper waits on, so one started just before the marker would keep reading. So:
  - every real-data command (the engine and the four commands above) takes `LOCK_SH` on `~/.local/state/betangel-suite/run/realdata.lock` before it creates anything, `TMPDIR` included, re-checks the marker under the lock, and holds the lock for its life. In Nuance's words: "Every marker-checked command takes LOCK_SH before TMPDIR, re-checks the marker under it and holds it for life". Nuance wrote that at 93e26e6, when `test` and `vendor` were not yet marker-checked;
  - headless commands also check the marker between members, and the catalogue is built under a temporary name and renamed into place;
  - Nuance's wrapper takes `LOCK_EX` on it. It waits at least 60 s for the lock, then refuses its own run (fails closed) if it is still held ("The wrapper waits 60 s+ for LOCK_EX, failing closed", Nuance's PR #2 review, item 6). It is a separate lock, not `engine.lock`: in Nuance's words, "not engine.lock (stop would fail with control_failed)" (Nuance's probe);
  - I-17 has one test per marker-checked command (section 10);
  - **the lock's name is `run/realdata.lock`.** Nuance's PR #2 review had written `run/active.lock` for the same lock. In Nuance's answer to lab-Claude's question 3 of 2026-10-17 (PR #2 re-review), `realdata.lock` "is right", and the other name "was my slip for the same lock".
- **The real-data lock as built** (596d052, 18de53e, fbbc0c3):
  - **Who takes it.** Every real-data command (`cli.REALDATA_COMMANDS`: `serve`, `open`, `ssh-session`, `catalogue`, `selfcheck`, `diagnose`, `ledger-summary`) takes `LOCK_SH` on it without waiting (`run_lock_busy` while the wrapper holds it). It checks that the file is still the one at the path, checks the marker again under the lock, and only then creates its `TMPDIR`. It holds the lock until it exits. `cli.main` refuses `run_lock_not_held` for any other command whose `TMPDIR` would be made under `~/betangel-data`. `stop` and `vendor` make no `TMPDIR` (`cli.NO_TMPDIR`), so neither the check nor the lock applies to them (96d0bcc).
  - **Why the marker is checked after the lock** (a lab probe): macOS `flock` grants a new `LOCK_SH` while a `LOCK_EX` waits. So a command that locks after the marker appeared refuses at once and lets go, and one that locked before is waited for.
  - **Who does not take it** (lab-Claude's decision, which Nuance agreed on four conditions in Nuance's answer to lab-Claude's question 2 of 2026-10-17, PR #2 re-review): `test`, `uisnap` and `vendor`. None of them reads a data root or writes under `~/betangel-data`, and the guard refuses both in their modes: writes from the start, reads since 0a3ed65 (`data_home_read_refused`, within the limits section 10 names). Each refuses under the marker at start, and holding the lock would let a long test run make the wrapper fail closed. Nuance's conditions, and what this branch did:
    - condition 1: the docs said "never reads a data root" while the guard refused only writes, so that rested on how the commands are built; Nuance asked to say so or to refuse reads under the real data home, preferring the second. Lab-Claude took the fail-closed option (0a3ed65);
    - conditions 2 and 3: `uisnap` and `stop` keep guard modes of their own, with the state root as their only write root, never the suite root (8102f99). Until then `cli.py` mapped both to engine mode; Astra's re-review of PR #2 found the same for `uisnap` (engine mode "can write its synthetic suite root"), while judging `test` and `vendor` taking no lock "reasonable for their current restrictions";
    - condition 4: a test running when the marker appears is bounded by the per-test stop and Q-N14's per-module check (above).

    `stop` takes nothing and makes no `TMPDIR`: it must work during a run. On this branch `cli.main` refused it with `run_lock_not_held` until 96d0bcc, because its `TMPDIR` lay under `~/betangel-data`; since 8102f99 its `TMPDIR` is the state root's `tmp/`, which it still does not make. phase0/http and phase0/viewing had the exemption already.
  - **Where it is.** In the state root's `run/`, beside `engine.lock`, which Nuance's wrapper already reaches. A lock under `suite.noindex` would need `suite.noindex` and its `run/` made before the locked re-check, which Nuance's item 6 rules out, and only the engine may write the suite root.
  - **The file.** The suite makes it once (0600) and never unlinks, renames or replaces it, and the guard refuses those calls (`run_lock_protected`): a holder of an old file and a wrapper locking a new one would not exclude each other. As the suite assumes the wrapper: it opens the file `O_RDONLY|O_NOFOLLOW|O_NONBLOCK`, counts a missing file as free, and never creates, truncates, renames or removes it. A lock file that is not a regular file owned by this user, with one link and no group or other write bit, makes every real-data command refuse (`run_lock_invalid`). So does a lock file that cannot be opened or locked, and a `run/` that cannot be made, as under a state root this user cannot write (c5fe696). Its directory `run/` is protected the same way: renaming or replacing `run/` would move the lock with it and split it as above, so the guard refuses a rename, replace or link at or from `run/`, even while `run/` is missing (lab-Claude's round-4 review; 6aeb1d5). `os.rmdir` stays allowed: it removes only an empty `run/`, which holds no lock. Those refusals hold `run/` and the lock where they are named, so in every mode `arm()` refuses a `run/` or lock that is a link, or that it cannot look at (`run_lock_invalid`), as `hold_shared` already did: through a link the lock would lie where no refusal reaches (the guard-paths review; b0d5c0d).
  - **Headless commands.** `catalogue`, `selfcheck --sample N` and `diagnose` call `runmarker.require_clear()` between members and stop at the first marker. The catalogue is written to a temporary name in its own directory and renamed into place (`os.replace`), so a stopped run leaves no partial catalogue. Owed when the catalogue is built; the writer helper will need a replace function, because `write_new` refuses existing names.
  - **Lab-runs.** The suite never creates or removes `lab-runs/ACTIVE` or `lab-runs/LOCK`, and the guard refuses any suite write in `lab-runs/` (`write_outside_roots`; tested in fbbc0c3). That rested on `lab-runs/` lying outside the roots, which a state root linked to `~/.local/state` undid: `arm()` succeeded, and removing `ACTIVE` or renaming `LOCK` was allowed (Nuance's PR #2 re-review, F5). Since c3b0c61, `arm()` in every mode, and the writer helper, refuse a write root or `TMPDIR` in, around or onto `~/.local/state/lab-runs` (`root_overlaps_lab_runs`), stat calls only (section 3.7).
- **Mid-session.** The actor checks the marker every tick and before every journal append or ledger write. If the marker appears:
  - the engine pauses the clock and freezes `PaperExchange`: no advance, no activation, no journal or ledger writes;
  - the UI shows why;
  - an attached `ssh-session` sends the engine nothing and exits, and Yu's terminal shows `ended reason=run_marker` (lab-Claude's reading, kept in round 5; built on phase0/viewing);
  - the engine exits after a grace period of 30 s without writing under `~/betangel-data`. It leaves only a code-only note in the state root, `run/interrupted/<session_id>`, saying why (section 7.10).

  So the engine may hold `realdata.lock` (shared) and `engine.lock` for about 35 s after the marker appears, until it exits. An attached `ssh-session` (phase0/viewing) could hold `realdata.lock` longer until round 4b, which made it check the marker before every poll (e9729a6 on phase0/viewing), so the 35 s bound stands (see "Owed on phase0/http and phase0/viewing" below). Nuance's PR #4 terms allow for that: Nuance's wrapper waits at least 60 s for it (Q-N3), and Nuance measured the lock free only after 30.23-30.60 s (PR #4 review, item 15).

  At the next start, after the run, the session is marked `interrupted_run`, and its open orders are swept from the journal (section 7.10). It is not counted as abandoned by Yu.
- **The marker is a stop request, not an instant barrier** (Astra's PR #1 review, item 4). Once it exists, no engine or real-data command starts. One already running drains: the engine stops at its next tick (it freezes with no journal or ledger writes and exits within the 30 s grace period), and a headless command stops before its next member. A write already under way when the marker appears can finish, so the polling does not stop every write the moment `ACTIVE` appears. The interval that is protected is the upstream run itself, and the wrapper's locks guard it: Nuance's wrapper begins upstream work only once `engine.lock` is free and it holds `realdata.lock` exclusive, and by then every suite engine and real-data command has exited, since each holds `realdata.lock` shared for its life.
- **Nuance's side (Nuance's terms, Q-N3).** Before touching sources or data, Nuance's wrapper:
  - creates the marker with O_EXCL, holding only the job kind, the UTC start and the pid;
  - waits for `~/.local/state/betangel-suite/run/engine.lock` to be free. It waits at least 60 s for the lock, then refuses its own run (fails closed) if it is still held ("Wait at least 60 s for engine.lock, and fail closed if it is still held", Nuance's PR #4 review; Nuance measured the lock free only after 30.23-30.60 s, item 15);
  - takes `LOCK_EX` on `~/.local/state/betangel-suite/run/realdata.lock`. It waits at least 60 s for the lock, then refuses its own run (fails closed) if it is still held ("The wrapper waits 60 s+ for LOCK_EX, failing closed", Nuance's PR #2 review, item 6). Every engine and real-data command holds that lock shared, so this also waits for them.

  "At least 60 s" is a minimum: holders release within about 35 s, and the wrapper must not give up sooner. Nuance's PR #2 re-review settles the wording: "waits at least 60 s for the lock, then refuses its own run (fails closed) if it is still held", for both locks.

  Nuance's PR #4 review adds:
  - a missing lock file counts as free, and any other error as busy;
  - the wrappers run outside betangel_research;
  - the wrapper removes only its own marker, and only after the job exits.

  Nuance's PR #4 review also had the wrapper hold a flock on the marker for the job's life. Nuance's PR #2 review moves it: "The flock moves from ACTIVE to a never-unlinked lab-runs/LOCK held for the whole job; judge staleness only while holding LOCK (a flock on ACTIVE removed a live marker in two probed races)."
- **Owed on phase0/http and phase0/viewing** (lab-Claude's round-4 review). The lock is built and tested on this branch; the commands that serve and view are built on the later branches, which still owe:
  - `cli.main` keeps the `run_lock_not_held` check inside its `not in NO_TMPDIR` branch when this branch is merged into them. phase0/http has `NO_TMPDIR = ("stop", "vendor")`, as this branch now does, and phase0/viewing adds `release`; none of them makes a `TMPDIR` or takes the lock.
  - An attached `ssh-session` (and `open`'s attach path) is a real-data command, so it holds `LOCK_SH` for its own life. Until round 4b an attached `ssh-session` on phase0/viewing noticed the engine's end only at its next heartbeat (`HEARTBEAT_S` = 15 s, after a heartbeat write that can wait `WRITE_TIMEOUT_S` = 5 s), so after the marker appeared its hold could reach about 50 s (30 s of grace, then up to 15 + 5 s), not 35 s, leaving about 10 s of the at least 60 s that the wrapper waits for the lock. Lab-Claude's decision was to make it check the marker on every poll and exit, so that the 35 s bound stands and the stated bound is not raised (sent to Nuance for information on 2026-10-17). Round 4b did it on phase0/viewing (e9729a6).
  - The I-17 test for each real-data command (`serve`, `open`, `ssh-session`, `ledger-summary`, and each headless command as it is built) comes with its handler. On this branch the lock is tested through `catalogue` and `selfcheck` stand-ins.
  - Tests there that rename `run/` inside a guarded child (in `tests/test_control.py` and `tests/test_guard.py`) must change, because the guard now refuses it (6aeb1d5).
- **No automatic work.** The catalogue is rebuilt only on an explicit command, never on a head change, so nothing fires during Nuance's ingest.
- **Until Nuance confirms the agreement at the merge SHA** (Q-N3; agreed as built at 52a9edc, on conditions, section 3.7). Lab-Claude runs no real-data commands while a run is announced, and Yu is told before starting. No engine command runs on the lab with the real HOME (Nuance's condition, above, and condition (b) of section 3.7). **Nuance's recorded agreement of the marker is a Phase 0 exit criterion, and Phase 1b journal writes on real data do not ship without it.** Nuance's PR #2 item 6 is built on this branch (596d052, 18de53e, fbbc0c3), and Nuance's PR #2 re-review agrees it as built at 823c194, pending F4 and F5 (above). Both are fixed on this branch (ff35218, c3b0c61); the agreement is owed at the merge-candidate SHA.

---

## 7. Paper trading

### 7.1 Scope and the operator-click rule

- **What paper supports.**
  - LIMIT/LAPSE, one instruction per click, and whole-bet cancel.
  - Pre-off horse-racing WIN with one winner on a CLASSIC ladder (V9).
  - **The ladder type** (Nuance, PR #1 review, item 1: a conditional P1 that fails closed; for BASIC and PRO the condition holds). `book.py` takes the ladder type only from `priceLadderDefinition` (book.py:82-89, :459). Without the key, V9 refuses every click in paper mode with `ladder_not_classic` (validate.py:120-121), while the oracle has no ladder check (paper.py:232-251), so `PaperExchange` would have filled. Nuance found the key in none of the 2,121 definitions in the free 2017 samples (counts from the sample manifest).
    1. **Both counts are in.** The counts are Nuance's to run, as the data owner.
       - **BASIC.** Nuance's result (archive-audit at 4d7bcd3, counts only; Nuance's mailbox note of 2026-10-17 08:41Z, and Nuance's PR #1 re-review, finding 5): `priceLadderDefinition` is in 0 of the 12,208 BASIC markets of 2015-05..2016-04, of every country and market type, and no `priceLadder*` key appears in any group. That scope is neither the 12,200 GB/IE WIN markets of section 2.4 nor the 12,208 members of the PRO TAR, whose count it equals. In Nuance's words, "the condition holds, so it is a P1, no longer conditional". The PRO definitions were not counted then: "Only BASIC is indexed; the PRO TAR is not ingested yet, so M-PRO's count is still owed" (Nuance).
       - **PRO** (M-PRO's count; Nuance's mailbox note of 2026-10-19, counts only): the stock `archive-audit` at research main 0d32421, on `~/betangel-data/historic-pro` after Nuance's ingest (section 2.4), finds `priceLadderDefinition` in 0 of the 12,208 PRO markets of 2015-05..2016-04, anywhere in the member, before or after the cutoff. Month by month the market counts match BASIC's, each month with 0 carrying the key, and no key containing "priceLadder" appears in any audit group. The positive control: the same 29 `md.*` keys appear as in the BASIC count, each in all 12,208 markets but `md.settledTime` (12,114). The limit: the 94 `malformed_runner` markets were read only up to the bad definition, so for them the result is 0 in the part read. M-PRO's count is no longer owed.
    2. **Absent is the case, in BASIC and PRO.** Lab-Claude's decision of 2026-10-17, following Nuance's finding 5, made it the working case, and Nuance's PRO count confirms it: in Nuance's words, M-PRO "does not change my BASIC note", and "V9 `ladder_not_classic` still needs that note's remedies on PRO data too". So Nuance's U-10 (section 14), with a fact row, and any question to Yu on V9 under D-5 stand, and can start now. Any CLASSIC default goes only at the book.py:459 call site, for historical ODDS markets. Any change to V9 goes to Yu under D-5.
    3. **Until U-10, or a V9 ruling by Yu, lands,** every real paper click is refused with `ladder_not_classic`. Section 0 and the Phase 1b exit (section 12) depend on it.
    4. **A keyless synthetic variant** (a definition with no `priceLadderDefinition`) is required, not optional (in Nuance's words, it "is now required, not optional"). It is built on phase0/http in round 4b, as the generator's `no_ladder_definition` option (f23ba3f).
  - GB/IE comes from the catalogue filter, not from a V-rule.
  - PRO members only.
- **The OperatorClick rule.** It enforces AGENTS.md:9 for this repo.
  - On an engine with real data roots, `PaperDesk.place`, `.cancel` and `.withdraw` take an `OperatorClick`. It is minted only by the per-request handler of `POST /api/v1/command`, carrying a fresh client nonce.
  - No timer, replay-loop or calculator code path can construct one. An AST test asserts that `OperatorClick(` appears only in `api/routes.py` handlers.
  - The green-up calculator only previews. Yu's Enter or click submits.
  - **What it proves.** I-8 is a code-path property: no suite code path creates an order without an HTTP request carrying a valid session token and a fresh nonce. It is **not** proof that a human clicked. Any holder of the token could POST (section 9.2). Like `presence.py`'s line (presence.py:1-11), it is friction and provenance, not identity. The agent-conduct rule covers the rest (section 3.9, rule 6).
  - **The gap: cleanup that no request starts** (Nuance's PR #1 re-review, finding 1; Astra's PR #1 review, item 2). As written above, `.cancel` and `.withdraw` need an OperatorClick, yet `bin/suite stop` (the `run/STOP` poller), the watch-grace and `max_session` timers, a stop signal and next-start recovery all cancel or withdraw with no request (sections 7.6 and 7.10). Either the AST test would fail or those paths would bypass `PaperDesk`. These paths only reduce, so the gap is not a P1 (Nuance).
  - **Proposed: a system stop that can only reduce** (lab-Claude's proposal of 2026-10-17, in the shape Nuance prefers; asked of Nuance and Astra in the round-5 replies, and recorded as moot under RS-1a of proposal 003 on 2026-10-19, section 2.2.1):
    - one method, `PaperDesk.stop_all(SystemStop)`. It takes no targets: it applies STOP's order handling (section 7.6) to every pending and EXECUTABLE order of the session, or at the next start the sweep of section 7.10, and nothing else;
    - a `SystemStop` is minted only in the `run/STOP` poller, the session-end paths (watch-grace expiry, `max_session`, stop signals) and next-start recovery, each with its reason;
    - `.place` never takes one, and nor do `.cancel` and `.withdraw`, so no system path can place, replace, or choose which orders to cancel;
    - the AST test is extended: `SystemStop(` appears only at those sites, and `stop_all` is the only `PaperDesk` method that accepts one (owed at 1b);
    - the journal records `halt {reason:"system_stop:<reason>", scope:"global"}`, never `operator_stop`, and no system reason starts with `operator_`;
    - tests for `bin/suite stop`, expiry (`abandoned`, `max_session`), failure (`engine_failed`, which leaves its orders to the next start's sweep) and recovery, none of which fabricates a click (owed at 1b).

    It changes a safety invariant (I-8). Under the governance row (section 3.9), Nuance and Astra each say whether it widens, and it goes to Yu (rule 10) unless both say it does not. Since the question is moot under RS-1a (section 2.2.1), neither their answer nor Yu's ruling is pending, and this document does not adopt the proposal.
- **Scripted orders.** `TestOrder` (also used as `ReplayedClick` for `commands.jsonl` re-runs) is a separate type. `PaperDesk` accepts it only when the engine is in synthetic mode, and synthetic mode refuses every configured real data root. A `commands.jsonl` re-run writes only to a temp journal in that mode.
- **Live-parity mode** offers only what live v1 allows: whole-bet cancel, no replace or drag, no partial cancel, LAPSE only. It is ON by default unless Yu picks "learn ladder trading" (R-7).
- **Exploration mode** shows an amber banner: "paper-only: not available live under D1-D5". It adds paper replace (paper.py:383), drag-to-move (a replace), and size reduction. With R-7 = ladder trading it arrives in Phase 1b and is the default; otherwise it arrives in 1c and is off by default. Sessions with replaces are "parity not checkable".

### 7.2 Parameters, commission and cap profiles

- **Params.** `PaperExchange(params)` gets exactly the `PARAM_KEYS` set (paper.py:59-60), which `_check_params` validates (paper.py:68-84):

  | Param | Value |
  |---|---|
  | `model` | `paper-v1` |
  | `submit_latency_ms` | 500 |
  | `displayed_size_fraction` | 0.5 |
  | `passive_fills` | `trd_queue_conservative` |
  | `traded_volume_divisor` | 2 |
  | `max_snapshot_age_s` | 10 |
  | `commission_rate` | 0.02 |
  | `commission_source` | per R-3 |

  These are the repo's own `orders.paper` defaults (config.py:65-66) plus the required commission fields.
- **Cap profiles.** Both are inside `ABSOLUTE_CEILINGS` (constants.py:197-217), so no policy change is needed. Both are validated by `config.validate_config`. They are enforced by suite code, not RiskGuard. The default follows R-7.

  | Profile | Stake | Liability | Market | Total | Daily loss | Orders/min | Max ticks from best |
  |---|---|---|---|---|---|---|---|
  | `v1-live-mirror` (default for "practise live v1") | £2 | £10 | £20 | £50 | £20 | 6 | 10 |
  | `practice` (default for "learn ladder trading") | £50 | £100 | £200 | £500 | £200 | 30 | 50 |

  Paper stakes above £50 would need a ceilings change (P-6).
- **The live v1 shadow badge.** Shown on every order and in the debrief. It flags anything live would refuse today:
  - stake, liability or rate above the DEFAULTS caps (config.py:58-62);
  - more than 30 minutes before the off (V9b, validate.py:122-130);
  - a second order in a market while one is unresolved (R3);
  - any replace, drag or size reduction;
  - **the R10 line:** a click live R10 would refuse because the UTC day's booked worst case plus the new order's would pass £20, counted as live counts it (risk.py:369-379; journal.py:678-686, :841; Nuance's citations, PR #1 re-review, finding 10). In Nuance's probe at 76f71dc, after two green-ups that the practice figure (below) counts as +78p, live has 1520p booked and refuses a third order.
- **Practice stop** (draft 0.2 called it the practice loss limit). A paper-only stop that follows the active cap profile: £20 a day under `v1-live-mirror`, mirroring `max_daily_loss`, and £200 under `practice` (the table above). Whether to have it at all, and its amounts, are Yu's (Q-Y6). When it is reached, paper is disabled for the rest of the day, with an explanation.
  - It is never the journal fold's daily figure. The fold books each order's worst case, so in Nuance's probe a +£3.27 green-up counted as −£36.66 (PR #1 review). Live's view of that figure is the R10 line above, not the stop.
  - Its definition is lab-Claude's proposal, revised in round 5 with Nuance's answer to lab-Claude's question 9 of 2026-10-17 (PR #2 re-review: "Agree no separate store and net-across-sessions, voided included") and Nuance's PR #1 re-review, finding 10; Yu can override it:
    - **the day** is upstream's: the UTC day, aligned to the epoch (risk.py:311), because the `v1-live-mirror` amount mirrors `max_daily_loss`. The `practice` profile uses the same day, so the two agree (lab-Claude's choice). It is the wall-clock day, never the replayed race's date. `session.json` records each session's UTC start, and a session counts in the day it started, even if it runs past midnight;
    - **the figure** is the sum over that day's sessions, voided and interrupted ones included. A session with an official paper-v1 net (a `completed` session whose market is not excluded) counts that net. Every other session counts its worst case: the worst outcome of its matched position, with every still-matchable or unknown portion at its full adverse loss;
    - **the store** is none of its own: the figure is recomputed from each of the day's sessions' `session.json` and journal fold under the suite root, plus the open session in memory. If any of them cannot be read, paper is refused (fail closed);
    - **when** it is checked: before every place, as live R10 is (risk.py:369-379), not only once the limit is reached. A click is refused if the day's loss on that figure, plus the new order's worst-case loss, would pass the stop.
  - Tests are owed with it in 1b: a session over midnight, a voided and an interrupted session, an unreadable session (refused), and the check before the click.

### 7.3 One click, step by step

1. **The UI sends** `{nonce, cmd:"place", selection_id, side, price_h, size_p}`. The handler mints an OperatorClick and enqueues it.
2. **Build the order.** At replay time T (an integer ms), the actor reads `anchor()` (journal.py:437) and materialises `book = materialise(M)` (section 6.2).
   - It builds the instruction v1 `{selection_id, handicap 0, side, price_h, size_p, persistence_type "LAPSE"}` (`validate_instruction_v1`, schemas.py:222).
   - Refs come from `make_customer_order_ref` and `make_customer_ref`, with a deterministic rng `sha256(session_id:click_index)` (validate.py:46-55), passed as `lambda n: rng(n)` so a falsy rng never falls back to `secrets` (section 4.1).
3. **Validation.** Let `state = folder.state(now_ns=T * 1_000_000, submitting_as_unknown=False)`, and `market_orders = [o for o in state["orders"].values() if o["market_id"] == M]`. The fold's `orders` is a dict keyed by ref, so it is never passed as is, as the oracle does at paper.py:884-885. Then:

   `validate.validate_place(M, [instr], book=book, open_orders=market_orders, config=<paper config>, mode="paper", now_ns=T * 1_000_000, customer_ref=cref, customer_order_refs=[ref])` (validate.py:290-291).

   On any failure the click is refused and its rule code is mapped to plain English. Nothing is journaled. The refusal table covers, among others:
   - V0: "unsupported order shape (only LIMIT/LAPSE)";
   - V5: "below £1";
   - V6: "only LAPSE (cancel at in-play) is supported";
   - V8: "would match your own order";
   - V9: "suspended, in-play, not WIN or book invalid", with the sub-reason, for example `book_invalid` or `ladder_not_classic` (the latter on every real click until U-10, or a V9 ruling by Yu, lands; section 7.1);
   - V10: "no market change for 12 s; paper-v1 treats the book as stale" (section 7.5);
   - V13: "more than N ticks from best";
   - V14: "profit-ratio rule".
4. **Journal.** Three events are appended:
   - `intent` with `{order, customer_strategy_ref, is_probe:false, parent_ref:null, provisional_child:false, source:"paper_replay"}`, `expect_head=anchor`;
   - `submit` with `{action:"place", instruction_count:1, body_sha256:null, transitions:[SUBMITTING]}`;
   - a `note` with the operator-click provenance: nonce and UI mode, never the token and never a key named `session`, `token`, `headers` or `authorization`.
   
   Notes on these events:
   - `customer_strategy_ref` is `suite-click` for operator sessions and `suite-test` in synthetic tests, equal to the paper config's `orders.customer_strategy_ref` (section 3.8). This lets journals separate clicks from scripted tests. `INTENT_PAYLOAD_KEYS` is an exact set (journal.py:95-96), so no provenance field can be added to the intent itself.
   - These are the event shapes of `_journal_order` (paper.py:812-825). The intent source is `paper_replay` (INTENT_SOURCES, journal.py:97) until Nuance adds a distinct paper source (U-9).
   - `expect_head` refuses a double submit from a second engine or a stale tab (journal.py:483 docstring).
   - The journal is constructed as `OrderJournal(path, mode="paper", clock=sim_clock)`. The clock is a suite `SimClock` on the pt axis that never moves backwards (as `_SimClock`, paper.py:667-686).
5. **M enters exact mode.** If M was in display mode, the exchange is first re-seeded (section 7.4), and `prev = materialise(M)`. The order is now **pending**: SUBMITTING, with no `bet_id` until activation (paper.py:324-326).
6. **Activation at A = T + 500.** This follows `_simulate` exactly:
   - at the first yield with pt > A, call `PaperExchange.place([order], book=prev, now_ms=T)` *before* advancing to that yield (paper.py:878-881);
   - if a yield has pt == A, activate after the **last** yield at that pt (paper.py:896-902);
   - if the CLOSED snapshot arrives first, an order with A == its pt is activated against it. An order with A after its pt is activated after the loop against the CLOSED book (`book=prev`, the last yield; paper.py:899-908);
   - if the member ends before any later yield of M, the order is activated against the last yield the same way (paper.py:907-908).
   
   In those last two cases the result is REFUSED `paper_book_stale` when the book is too old. Otherwise it is FAILED `paper_rejected_market_state` for a non-OPEN market (paper.py:232-251, :310-312; lifecycle.py:195-196). Both are journaled like any activation.

   `lifecycle.classify_place_report` (lifecycle.py:243) gives the move, and a `report` event is journaled. Immediate fills take at most `floor(level size × 0.5)` per level. The rest rests, with a known queue (`queue_state()`, shown as "Q £x ahead") or an unknown one ("queue unknown: will not fill").
7. **Each later yield.** `PaperExchange.advance(market_orders, prev_book=prev, book=cur, now_ms=pt)` (paper.py:428), with `market_orders` built as in step 3. Updates that change fields or state are journaled as `report {paper_advance:true}`, as in paper.py:887-895.

### 7.4 Exact stepping and the parity contract

**What exact mode reproduces.** From the moment M enters exact mode, the suite feeds `PaperExchange` the same snapshots, in the same order and with the same activation rule as `_simulate`. That includes:

- the unstamped activation book, so the first post-activation interval is skipped as `passive_fill_skipped_pre_activation_interval` (paper.py:496-503), exactly as in the oracle;
- 503 windows, which give unusable books with no fills but still raise high-water marks;
- activation at CLOSED and at the end of the member (section 7.3, step 6).

**The one gap: traded high-water marks from before exact mode.** `advance` raises per-(selection, price) traded high-water marks from every valid snapshot (paper.py:552-553, :558-570). Volume below an earlier peak never counts again. In display mode the suite does not call `advance`, so peaks from before exact mode would be missing. Missing peaks would let a dip-and-recovery count as new volume, which is *less* conservative than the oracle.

**The fix: conservative re-seeding.**

1. **The tracker.** `replay/hwm.py` keeps a running maximum of every raw `trd` size per (selection, price) in M, over messages with **pt ≤ V only**.
   - It uses the same conversions as `_traded`: `to_hundredths(Decimal(repr(float(price))))` and `Decimal(repr(float(size)))`.
   - It advances with the replay clock, is part of every checkpoint, and is restored with the cache on seek (section 6.4).
   - **It is never seeded from the prescan's end state.** The prescan runs to the end of the member. Future traded volume in the mark would make `delta = now − max(prev, hwm) ≤ 0` at every later step (paper.py:532-537), so nothing would ever fill passively. That would be a look-ahead leak. `_load_state` accepts whatever `traded_hwm` it is given (paper.py:212-220), so nothing upstream would catch it.
2. **The re-seed.** When M enters exact mode, the actor rebuilds the exchange with public interfaces only: `PaperExchange(params, queues=ex.queue_state(), state=merge(ex.export_state(), traded_hwm=max(existing, raw_max_at_V)))` (paper.py:170-179, :184). The state format is contract-tested (paper.py:58, :194-230).
3. **Why it is conservative.** Every value the oracle's high-water mark could hold at V is one of the raw values seen up to V. So the suite's high-water mark is **at least** the oracle's at every step.
4. **When it changes nothing.** When trd never decreases, the re-seed changes nothing: the raw maximum up to V equals the current value, which the oracle also holds.

Nuance accepted the suite-built `state` (Q-N7, PR #1 review; Yu can override), with a fresh exchange per attempt and finite trd values only. Its test is in the 1b exit. The proposed upstream helper is U-6.

**The parity contract**, tested in `tests/test_paper_parity.py`:

| Case | Claim | How it is tested |
|---|---|---|
| Place-only scripted sessions, orders that pass `validate_place`, unstamped books, fixtures where no runner's traded volume ever decreases and no trd precedes the first definition. Includes orders still pending at CLOSED and at the end of the member. | **Equal**, field by field: `final_state`, `size_matched_p`, `average_price_matched_h`, `size_lapsed_p`, `refusal`, `flags`, `activation_pt`, `activation_book_pt`, and settlement gross, commission, net and `excluded_reason`. Refs are excluded: the oracle derives them from the orders-file sha (paper.py:842-843). | In synthetic mode, the suite's scripted session (`TestOrder`) is exported as an orders file (`{schema_version:1, orders:[{submit_pt, market_id, selection_id, side, price, size}]}`, ORDER_FILE_KEYS paper.py:61). It is run through `run_paper_replay` in a temp dir. |
| Re-seeding mid-market when later trd at the order's price is higher | **Equal** passive fills: no look-ahead. | A fixture with rising trd after the re-seed point. |
| The same, on fixtures with trd dips, images and pre-definition trd | **Conservative.** Suite high-water mark ≥ oracle's at every step. Total matched size per session ≤ oracle's is a *tested property, not a proof*. | Randomised fixtures with fixed seeds. |
| Sessions with cancels, replaces or pending-order withdrawals | **Not checkable**: the orders file has no cancels (paper.py:61), and the oracle has no withdrawal. The session is labelled "parity not checkable". | U-3 proposes cancels upstream. |

Parity runs only on small synthetic fixtures; `run_paper_replay` materialises everything (paper.py:991-996). No routine parity run is ever made on real sessions.

### 7.5 Quiet-market staleness

- **The artefact.** Historical files record only changes. A quiet pre-off market can go more than 10 s without a message. Paper V10 (validate.py:154-163) and `_activation_refusal` (paper.py:232-251, stale at :249-250) measure age from the snapshot's pt. That pt is the pt of the market's last change, so clicks in such a spell are refused as stale (`book_stale` / `paper_book_stale`).
- **It affects the oracle too.** The oracle (and therefore P1) has the same artefact: its activation book's pt is the market's last change.
- **It is rare where practice happens.** *Measured (real, aggregates)* on 40 random members, 39 of which flipped in-play:
  - in the last 10 minutes, the per-market maximum gap had a median of 1.35 s, a p90 of 2.67 s and a maximum of 17.2 s;
  - only 1 of 39 markets had any gap over 10 s;
  - from T-30 to the off, 13 of 39 markets had such gaps, 36 in total.
- **MVP: parity only.** Unstamped books are used. The refusal is explained plainly ("no market change for 12 s ...") and counted in the debrief, split by time to the off (Nuance, Q-N6).
- **Cut from the MVP.** The draft 0.1 opt-in "quiet-book relaxation" (`quiet_books_stamped`) is removed. It is revisited only if the debrief counts show it matters (U-8): Nuance keeps U-8 parked, and revisits it if stale refusals show in T-10 to the off (Q-N6).

### 7.6 Cancel, pending orders, STOP, lapse at the off, close and settle

- **Cancel (whole bet, EXECUTABLE orders).** This mirrors the gateway's paper sequence (gateway.py:1391-1485), without RiskGuard. Let `bet_ids` be the targets and `cancels = [{"bet_id": b, "size_reduction_p": None} for b in bet_ids]`.
  1. **Validate.** `state = folder.state(now_ns=T*1_000_000, submitting_as_unknown=False)`, `market_orders = [o for o in state["orders"].values() if o["market_id"] == M]`, then `validate_cancel(M, cancels, open_orders=market_orders)` (validate.py:410).
  2. **Snapshot the EXECUTABLE records before journaling anything.** `before = [dict(o) for o in market_orders if o["bet_id"] in bet_ids]` (as gateway.py:1478).
  3. **Journal the submit.** `cancel_intent` with `bet_ids`, and a `submit` with `{action:"cancel"}` moving the orders to CANCEL_PENDING.
  4. **Map the post-submit records.** From the post-submit fold, `by_bet = {bet_id: <CANCEL_PENDING record>}` (as gateway.py:1432-1435).
  5. **Cancel and classify.** `report = PaperExchange.cancel(before, cancels, now_ms=T)` (paper.py:358). Then `classify_cancel_report(report, sent_bet_ids=bet_ids, orders=by_bet)` (lifecycle.py:306; as gateway.py:1461), then a `report` event.
  
  `PaperExchange.cancel` cancels only records whose state is EXECUTABLE (paper.py:372-373). Passing it the CANCEL_PENDING records would return `BET_TAKEN_OR_LAPSED`, which `classify_cancel_report` turns into UNKNOWN (lifecycle.py:295-297), leaving the market unresolved. A test asserts that a full paper cancel ends in EXECUTION_COMPLETE with `size_cancelled_p` equal to the remaining size, never UNKNOWN.

  Cancels are instant in paper-v1, and the UI says so.
- **Pending orders (SUBMITTING, before activation).** For 500 ms after a click, an order has no `bet_id` (paper.py:324-326). The upstream cancel interfaces work only by `bet_id` (paper.py:362; validate.py:322-327, :439-442), and the oracle has no cancel. What a cancel command does to a pending order depends on the mode. The rule is Nuance's answer to Q-N5 (PR #1 review, 2026-10-16) and Nuance's answer to lab-Claude's question 5 of 2026-10-17 (PR #2 re-review); Yu can override both. How the suite carries it out is lab-Claude's decision of 2026-10-17.
  - **In live-parity mode a pending order activates, then is cancelled.** In Nuance's words: "The 500 ms models an order in flight and step shows the activation book, so in live-parity Esc on a pending order activates then cancels; withdrawal only for void and badged exploration; readers use the folded error_code." And on STOP: "Yes — STOP is covered. The 500 ms models an order in flight no live STOP can recall, so in live parity STOP activates each pending order at its own A then cancels the unmatched, as Esc does (one code path for Esc/Z-X/Shift-Esc/own-click/STOP)."
    - One code path serves Esc, Z, X, Shift+Esc, clicking our own order and STOP. Each marks its pending targets. A marked order activates at its own A exactly as in section 7.3, step 6, and may take immediate fills. Its unmatched rest is then cancelled by the cancel sequence above, in the same actor step.
    - While the replay runs, that happens when the replay reaches A. While it is paused, a marked order activates when play or a step next passes its A. That Esc, Z, X, Shift+Esc and a click on the order wait for the replay to reach A, while STOP steps at once (below), is lab-Claude's reading of Nuance's answer; it was asked of Nuance in the round-5 replies (round 5 close), and since 2026-10-19 it is recorded as moot under RS-1a of proposal 003 (section 2.2.1).
    - STOP, which freezes the clock, does not wait. It steps the reader and the exchange, never the display, to each pending order's A, applying every yield of M on the way as exact mode does, activates the order there and cancels the unmatched rest. The frozen display does not move.
  - **In exploration mode (badged) a pending order is withdrawn.** Any cancel command that targets it withdraws it. The actor removes it from the pending-activation list, and journals a `report {action:"place", paper_withdrawn:true}` moving SUBMITTING → REFUSED with a suite reason: `operator_withdrawn_before_activation` for Esc, Z, X, Shift+Esc and clicking the order; `operator_stop_before_activation` for STOP; `system_stop_before_activation` for a system stop (section 7.1, proposed).
  - **Void and rewind withdraws, in both modes, with its own reason,** `operator_void_before_activation`. In Nuance's words: "Split void's order handling from STOP's (void withdraws, per my Q-N5)".
  - **The marker freeze wins.** While the run marker freezes the engine (section 6.8), no order activates, is cancelled or is withdrawn, STOP included. Pending orders are left for the next start (section 7.10).
  - **Why a withdrawal is legal.** SUBMITTING may move to REFUSED (lifecycle.py:41), and `transition()` sets `error_code` to the reason (lifecycle.py:150-151). A dry-run `transition()` checks the move first. Readers use the folded `error_code` (Nuance).
  - **Parity.** A session with a cancel or a withdrawal is labelled "parity not checkable".
  - **Superseded.** Draft 0.2 withdrew a pending order in every mode, so that it could take no immediate fill the operator had tried to prevent. Nuance's answer to Q-N5 replaces that for live-parity mode. Withdrawal now serves only exploration mode, void and next-start recovery (section 7.10).
- **Keys and commands.** Each is one OperatorClick per command. A pending target is handled as above (activated, then cancelled, in live-parity mode; withdrawn in exploration mode), and an EXECUTABLE one is cancelled:
  - Esc: the last unmatched order, which may be pending.
  - Z: every back on the runner. X: every lay on the runner.
  - Shift+Esc: every order in the market.
  - Clicking our own order in the ladder: that order.
- **STOP** (button, Q, or `bin/suite stop`, which writes `run/STOP`; the engine polls it at 4 Hz):
  - freezes the clock;
  - handles every pending order as above (in live-parity mode it steps the reader and the exchange to each one's A, activates it and cancels the rest; in exploration mode it withdraws it) and cancels every EXECUTABLE paper order by the cancel sequence above;
  - journals `halt {reason:"operator_stop", scope:"global"}` for the button and Q, which are OperatorClicks. `bin/suite stop` reaches the engine through the `run/STOP` poller, with no request, so it is a system stop: under the proposal in section 7.1 it journals `halt {reason:"system_stop:cli_stop", scope:"global"}`;
  - refuses new paper orders until the operator types `resume`.

  STOP does not end the session. `bin/suite stop` then also stops the engine, so the session ends as `stopped`; the button and Q do not (section 7.10).

  `killswitch.engage` is never called on the lab. It would create the repo's global KILL file under the real state root.
- **Void and rewind** withdraws every pending order (`operator_void_before_activation`), cancels every EXECUTABLE one by the cancel sequence above, then closes the session (section 6.4).
- **At the off.** `advance` lapses unmatched size at the first in-play snapshot (`lapsed_inplay`, paper.py:474-480): Bet Angel's "At In-play: Cancel".
- **At CLOSED:**
  1. Any order still pending is activated against the CLOSED book or the last yield (section 7.3, step 6), and journaled.
  2. Any remaining EXECUTABLE size is lapsed with a suite-built move equal to `_lapse`'s result (paper.py:585-590):
     - state `EXECUTION_COMPLETE` if matched > 0, else `LAPSED`;
     - `size_lapsed_p += remaining`; `size_remaining_p = 0`.
     
     It is journaled as `report {paper_advance:true}` with reason `paper_market_closed`, as at paper.py:913-919, and checked first with `lifecycle.transition` (lifecycle.py:103). U-4 proposes a public helper.
  3. `PaperExchange.settle(orders, market_definition=<closed snapshot>)` (paper.py:592), then a journaled `settle {commission_p, transitions}` (as paper.py:920-927).
  4. `close_market(market_id, refs)` (paper.py:259), then `journal.verify()` (journal.py:410), whose result is recorded in `session.json`.
  
  A member that ends without CLOSED is reported as `not_closed_in_recording`, with no settlement. Its pending orders are first activated against the last yield, as in the oracle.

### 7.7 Positions, What-If and exposure

- **Per runner:**
  - matched back and lay size, and average price;
  - P&L if that runner wins, which is the sum of `pnl.order_pnl_pence` over matched orders (pnl.py:24);
  - an unrealised "green value" at the current best prices, shown gross and net of 2%.
- **ExposureView** is suite code with two bases:
  - **paper** (worst case with hedge credit);
  - **live** (worst case without hedge credit, as live R8-R10 count it; STATUS_EXPOSURE_BASIS, risk.py:52).
  
  Unmatched, pending and unknown portions count at their full adverse loss in both bases. Tests check it against an independent exposure oracle written in the tests, on both bases and on randomised order sets. `risk` is not used as the oracle, because it is not pinned (Nuance, Q-N1; section 4.2). Showing both bases makes visible that greening at live defaults would use up the £20 daily cap.

### 7.8 Green-up / close trade (new suite code; an operator action)

- **Inputs.** For the selected runner: W = profit if it wins, L = profit if it loses (integer pence), and p = the current best opposite price.
- **Hedge stake.** `h = (W - L) / p`. Lay h if it is positive; back |h| if it is negative.
- **Rounding.** h is rounded to whole pence in the direction that maximises the worse outcome. Any price snap uses `ticks.snap` with an explicit direction that goes against Yu.
- **Checks.** The stake must be at least £1 (MIN_BET_PENCE_GBP) and pass `profit_ratio_ok` (validate.py:67). If not, the preview says why, for example "green needs £0.62 < £1 minimum".
- **Preview.** It shows both outcomes after the hedge and commission at 2% on positive market totals. It warns that paper takes at most 50% of the displayed size, so the hedge may part-fill and rest. C opens the preview; Enter submits one place.
- **Out of the MVP:** green-all, reverse greening and offsets. Any automatic follow-up order would be automation (P-1).

### 7.9 Rule 4 and honest settlement

- **The exclusion.** `pnl.market_realized` excludes every market with a REMOVED or REMOVED_VACANT runner (pnl.py:15, :53-54) and every dead heat (pnl.py:55-56). That is at least 49.5% of the engineering-year WIN markets.
- **The debrief** always shows the official paper-v1 result, for example "excluded: rule4_adjustment_not_modelled".
- **Indicative figure.** It appears only when **every matched portion was matched strictly after the removal cut-off**. In that case Rule-4 deductions cannot apply to Yu's bets.
  - **The cut-off** (Nuance, PR #1 review) is the latest, over all runners, of each runner's first move into REMOVED or REMOVED_VACANT, taken over the whole stream: not the earliest removal, and not the close. A test with two removals at different pts checks it.
  - **Label:** "indicative: Rule 4 cannot apply to bets matched after the last removal; removal timing is not in the fact register".
  - **Out of totals.** The indicative figure never counts in practice totals.
  - **Computation.** Gross is the sum of `order_pnl_pence`. Commission mirrors pnl.py:79-82 exactly:
    - `costs = evaluation.settled_market_costs({market_id: gross}, 0.02)`;
    - `commission_pence = math.ceil(round(costs["markets"][market_id]["commission"], 6))`.
    
    `settled_market_costs` returns a float commission (evaluation.py:155-157), so without the same rounding the two figures could differ by 1p. A contract test asserts that, for a market without removals, the indicative computation equals `pnl.market_realized`.
  - **Fill pts** come from the activation pt (immediate fills) and the yield pt of each `paper_advance` fill.
  - **Otherwise** the debrief says "not computable in paper-v1".
- **Dead heats** stay excluded.
- **Library filter.** "Only races with no non-runner declared before the off" is available.
- **Upstream proposal.** U-1 proposes Rule-4-aware settlement.

### 7.10 Journal, sessions, attempts and determinism

- **One session per market attempt**, at `sessions/<YYYY>/<MM>/<session_id>/` (0700). `session_id` is random (`secrets.token_hex(8)`), and `<YYYY>/<MM>` is the wall-clock month of the attempt, not the race's month. Agents never read `sessions/` (rule 5). The session holds:
  - `journal-paper.sqlite` (0600; hash-chained; WAL with fullfsync; *measured* about 4.3 ms per append, about 13 ms per click);
  - `commands.jsonl`: every command with its virtual pt, nonce and result code. It never has a key named `token`, `headers`, `authorization` or `session`;
  - `session.json`, which holds:
    - `session_id` (never a key named `session`), market id, plan, archive and member sha256;
    - the release commit and tree hash, the pin commit and the file-manifest sha, and the interpreter;
    - the paper params' and the validated config's `canonical_sha256` (never the config itself; section 3.8), the commission source and the cap profile;
    - the mode flags (parity, exploration) and the attempt number;
    - the session's UTC start on the wall clock, by which the practice stop counts it (section 7.2);
    - the end status and its reason (below);
  - `report.json`.
  
  All writes go through `receipts.atomic_write_json`, `append_jsonl` or the journal, which run `refuse_forbidden` and `assert_clean`. Tests write a real `session.json`, a `report.json` and a note through these writers.
- **End statuses.** Nuance asked for `stopped`, `max_session`, `engine_failed` and `interrupted_crash`, and for "STOP's order handling before any end" (PR #1 review, item 11). The design below is lab-Claude's proposal of 2026-10-17, revised in round 5 with Nuance's PR #1 re-review, finding 9, and Nuance's answer to lab-Claude's question 6 of 2026-10-17 (PR #2 re-review); Yu can override it. Every end has a reason code, and one map gives the status from the reason. No reason of a system end starts with `operator_`, so a system end never reads as an operator act.

  | Reason | Trigger | Status | Order handling |
  |---|---|---|---|
  | `closed` | the replay reached CLOSED | `completed` | settled as the oracle does (section 7.6, at CLOSED); no STOP handling |
  | `member_ended` | the member ended without CLOSED | `not_closed_in_recording` | pending orders activated against the last yield, as in the oracle (section 7.6); no STOP handling |
  | `operator_void` | void and rewind (section 6.4) | `voided_rewound` | void's own handling (section 7.6) |
  | `system_stop:abandoned` | the watch grace period expired with nobody watching (section 8.6) | `abandoned` | STOP's order handling, as a system stop (section 7.1, proposed) |
  | `system_stop:max_session` | the maximum session time ran out (section 8.6) | `max_session` | the same |
  | `system_stop:cli_stop` | `bin/suite stop` | `stopped` | the same |
  | `system_stop:signal` | SIGTERM, SIGINT or SIGHUP to the process that hosts the engine | `stopped` | the same |
  | `engine_failed` | an error the engine cannot continue from, such as an unexpected exception in the actor | `engine_failed` | none from memory; the next start's sweep |
  | `run_marker` | the run marker appeared (section 6.8) | `interrupted_run` | none (the freeze); the next start's sweep |
  | none (no note) | a crash, a kill or a power loss | `interrupted_crash` | the next start's sweep |

  - STOP from the button or Q does not end a session; it refuses new orders until `resume` (section 7.6).
  - **The freeze wins.** While the run marker exists, a stop, a signal, the end of the grace period or `max_session` ends the session as `interrupted_run`, with no order handling. In Nuance's words: "the freeze wins (stop/signals/grace/max_session all end `interrupted_run`)".
  - **`engine_failed` runs no paper step from in-memory state** (Nuance's condition). Its orders, like those of the two interrupted ends, are left for the next start's sweep.
  - **Why the engine ended.** Each row down to `system_stop:signal` writes its status into `session.json` while the engine still holds the session. Otherwise the engine writes only a code-only note with the reason, `run/interrupted/<session_id>` under the state root, which lies outside `~/betangel-data`, so the freeze allows it. The next start writes the status from that note; no note means `interrupted_crash` (Nuance's condition).
  - **Tests, owed in 1b:** one per row, from its trigger. Today only `abandoned` is tested (phase0/viewing); there `stopped` omits SIGHUP, and `run_marker` is not mapped to `interrupted_run` (Nuance's PR #1 re-review, finding 9, citing phase0/viewing api/server.py:608-614).
- **The next-start sweep** (MVP: no crash resume). At every engine start, after the run-marker check, every session that has no end status is swept from its journal, with no activation, no replay and no paper step from memory. A pending order has no book at A then, and the freeze allowed no activation, so this is a third withdrawal case beside void and exploration mode. Nuance agreed it, on conditions (answer to question 6) that the steps follow:
  1. `journal.verify()` runs first. Nothing is appended to a journal that fails it.
  2. The journal is folded with `submitting_as_unknown=False`. The default `True` would make the withdrawal illegal: in Nuance's probe at 76f71dc it gave `illegal_transition:UNKNOWN->REFUSED`.
  3. The journal's `SimClock` starts at the last journaled pt, so no append moves backwards. A fresh clock gives `clock_regression=True` (Nuance's probe).
  4. Under the proposal in section 7.1, the sweep is `PaperDesk.stop_all(SystemStop)` with the reason `recovery`, and it journals `halt {reason:"system_stop:recovery", scope:"global"}`. A SUBMITTING order is withdrawn (SUBMITTING → REFUSED, reason `recovery_withdrawn_before_activation`). An EXECUTABLE order is cancelled by the cancel sequence of section 7.6; `PaperExchange.cancel` needs only the folded records (paper.py:358-381). A CANCEL_PENDING order is completed as the instant paper cancel it was: EXECUTION_COMPLETE, with its remaining size cancelled (CANCEL_PENDING may move to EXECUTION_COMPLETE, lifecycle.py:46). A dry-run `transition()` checks each move first.
  5. The end status is written from the note, by the map above.

  A swept session is excluded from parity ("parity not checkable"), and each withdrawn order counts at its full adverse loss, in the session's figures and in the practice stop (section 7.2). Tests, owed in 1b: the sweep over SUBMITTING, EXECUTABLE and CANCEL_PENDING orders, with `verify()` first and no clock regression, after each of `engine_failed`, `interrupted_run` and `interrupted_crash`.
- **Positions** come from an incremental `JournalFolder` fed by the events `append` returns (journal.py:483, :689-726). The suite never calls `fold()` per frame (journal.py:444). A test asserts that the folder's state equals `OrderJournal.fold(..., submitting_as_unknown=False)`.
- **Determinism (synthetic mode only).** Re-running `commands.jsonl` as `ReplayedClick`s over the same synthetic member, into a temp journal, gives an identical journal fold and identical results (test). This re-run never runs on real data (R-6).
- **Abandoned sessions.** A session is marked `abandoned` only after its watch grace period expires with nobody watching (section 8.6). After a crash, it is marked `interrupted_crash` at the next start. Either way its journal stays readable.
- **MVP: no crash resume.** *Later:* journal `paper_state` in `note` events (journal.py docstring, PAPER_STATE_KINDS :88) for resume.

### 7.11 Fill-model caveats shown to Yu

`PAPER_ASSUMPTIONS` (paper.py:31-57) is shown verbatim. In plain terms:

- immediate fills take at most half of each displayed level;
- resting orders fill only from traded volume at their exact price, after the displayed queue ahead, divided by 2;
- cancellations ahead in the queue never help (paper.py:42-46);
- an unknown queue never fills;
- there is no virtual or cross-matched liquidity, so prices can differ from the Betfair website;
- 2015-16 liquidity is not 2026 liquidity;
- every figure is "paper simulation, not execution evidence".

**Queue tracker (display only).** For each resting order, the orders panel and the debrief show:

- the queue ahead at placement;
- the raw traded volume at its price since then;
- how far paper-v1's ÷2 basis has worked through that queue.

It is labelled "not a fill" and is never passed to `PaperExchange`. It shows Yu why paper-v1 did or did not fill. U-7 proposes a calibrated paper-v2 queue model.

---

## 8. UI

### 8.1 Principles

- Bet Angel's vocabulary appears in tooltips: one-click, ladder, close trade, What-If, EPIQ-style queue, practice mode.
- Practise the learning target R-7 sets (live v1, the stated default, until Yu picks). Anything beyond live v1 carries the shadow badge, and anything paper-only is amber.
- Data honesty is always visible: a permanent banner and orange PAPER tinting.
- **Layout.** Laid out for the Air's 13-inch Safari viewport, about 1470×830 pt. That fits one ladder comfortably beside the grid and the positions panel. Two or three ladders appear only on wider windows, such as the lab's screen.
- High-contrast option. Every action has a key.
- **No credential fields, ever.** The title is static: `betangel-suite`.

### 8.2 Screens

1. **Race picker (home)**
   - Calendar of the visible months, then meetings by venue, then races by first-published off time (Europe/London).
   - Columns: race name, number of runners, BSP market, "non-runner declared" badge, readability (from `files[]`), attempts, and your net if traded.
   - Shortcuts: Random unseen race (R), Next race at this meeting (N), Resume.
   - Filters: GB/IE (the catalogue filter), venue, field size, "no non-runner".
   - One line explains why research months are hidden, and shows the count of markets hidden because their month is in no split.
   - Spoiler-free by construction (section 5.3).
2. **Trading screen**
   - **Top bar:**
     - market title;
     - countdown on the replay clock: red under 60 s, flashing under 30 s, then "IN-PLAY +mm:ss" when in-play flips;
     - status chips: OPEN, SUSPENDED, IN-PLAY, CLOSED, "ladder partial after suspension", "503: data possibly stale", "book invalid: non-finite size";
     - the freshness banner (section 8.4) and replay controls (play/pause, speed, jump menu, scrubber with an LTP sparkline and markers for orders, fills and removals);
     - "Report a problem" (section 8.7).
   - **Left: one-click grid.** Cloth and name; best 3 back (blue) and lay (pink) with sizes; LTP; projected SP (labelled display-only); WOM %; P&L-if-wins in green or red, with What-If on hover. Clicking a price places a paper order at the current stake. Clicking a name focuses that ladder.
   - **Centre: canvas ladders** (one on the Air's viewport, up to three on wider windows). Columns:
     - our backs, with stake and queue-ahead;
     - available to back, with depth bars;
     - price (LTP highlighted);
     - available to lay;
     - our lays;
     - traded volume at the price (÷2 basis);
     - green-up P&L if closed here.
     
     Left-click in the back column places a BACK at that price; in the lay column, a LAY. Clicking our own order cancels it. A pending one is activated and then cancelled in live-parity mode, or withdrawn in exploration mode (section 7.6). Drag-to-move exists only in exploration mode (R-7). The wheel scrolls; L re-centres on LTP; price orientation is a setting.
   - **Right: positions and orders.** Unmatched orders with queue-ahead, the queue tracker and age; pending orders with a countdown to activation; matched bets with average price; per-runner position and P&L-if-wins; exposure on both bases; the green-up preview; the live v1 shadow badge for each order.
   - **Bottom:** an activity log (placed, matched immediately or passively, withdrawn, lapsed at the off, refused with the rule explained, settled) and a chart strip (LTP and traded volume for the focused runner over the last 10 min, with your fills).
3. **Market overview** (should). Every runner with LTP, projected SP near and far (display-only), total matched, volume %, and price range since open.
4. **Debrief** (at CLOSED)
   - Winner revealed.
   - The official paper-v1 settlement (gross, 2% commission, net) and the indicative Rule-4 figure where it applies (section 7.9).
   - Flat at the off; size lapsed at the off; fills (immediate or passive); fill rate and time resting; the queue tracker for each resting order.
   - Average prices against the final BSP. Commission as ticks needed to cover 2%.
   - Trades drawn on the chart; refusals by rule (stale books and invalid books counted); attempt number; parity status.
5. **Journal and caps**
   - Journal events and `verify()` status; operator actions; refusal codes.
   - Caps panel: live v1 defaults and the active profile's usage (stake, orders per minute, the practice stop's figure for the UTC day; section 7.2), with flags for what live would refuse, the R10 line included.
6. **Practice log** (Phase 1c). Daily and weekly totals: races, net, flat-at-off rate and refusals by rule. CSV export under `exports/` only.
7. **Settings and keymap (?)**
   - Stake presets: £2 (labelled "live v1 cap"), £5, £10, £20 and £50, within the active profile.
   - Start offset (default T-10 min), auto-slow and auto-pause, frame rate, sounds, orientation, contrast, and one-click versus confirm-each-order.
   - `PAPER_ASSUMPTIONS` verbatim.
8. **STOP (kill)** is always visible in the top bar and reachable by key and by CLI (section 7.6). It is labelled "STOP (paper)". The real kill switch arrives with live work on the Air.

### 8.3 Keyboard

Keys follow Bet Angel where that does not clash with replay control. They work only while the app tab has focus, and the browser's default action is suppressed.

| Area | Keys |
|---|---|
| Replay | Space play/pause; `+`/`-` speed; J then 1-6 jump (T-30/10/5/2/1/off); `[` `]` step 1 s while paused; `.` next pt batch; R random unseen race; N next race |
| Selection | Up/Down change runner; Tab cycle ladders; L centre on LTP; 1-5 stake preset |
| Paper | B back the focused runner at the best available-to-back price; A lay at the best available-to-lay price; Esc cancel the last unmatched order; Z cancel all backs, and X all lays, on the runner; C close trade (preview), then Enter to confirm; Shift+Esc cancel all in the market; Q STOP. A pending target is activated and then cancelled in live-parity mode, and withdrawn in exploration mode (section 7.6). |
| Help | ? keymap overlay |

There is no auto-keypress and no timed action, because those are automation. That rule lives in the `ui/` JavaScript, which the server cannot check: an order command that arrives with a valid token and a fresh nonce looks the same whoever or whatever sent it (I-8). So node tests are owed before 1b: a repeated key (`repeat: true`) sends nothing, and with fake timers no timer path reaches an order command (Nuance's PR #1 re-review, finding 3). Changes to these paths go to Astra, and to Nuance as well for paper keys: Yu narrowed UI-only on 2026-10-17 (section 3.9).

### 8.4 Freshness banner and labels

- **The banner is always visible**, for example: `REPLAY · PRO · 2015-11-07 14:05:12 (virtual) · last market change 3.2 s ago · speed 2x (effective 2x) · PAPER paper-v1 · live-parity`.
- **Tints.** The PAPER border tint is orange. Exploration mode adds an amber chip. A pause gets a reason chip: "paused: not watched", "paused: Nuance run in progress" or "paused: STOP".
- **Later sources:** `DELAYED (up to 180 s, 3 levels)` (constants.py:164-167) on the Air, and `LIVE` only in the native shell. Paper never runs on `LIVE` data (section 2.3).

### 8.5 Rendering and update rates

- **Code.** Vanilla ES modules, no framework, build step or external request. The ladder canvas uses fixed 18 px rows and about 35 visible rows, and redraws on `requestAnimationFrame` only when a new frame has arrived. The grid and panels are DOM, patched by key.
- **Rates.** Engine frames at 10 Hz or less (configurable 5-20); countdown at 10 Hz; chart at 2 Hz.
- **Transport.**
  - The server sets `protocol_version = "HTTP/1.1"`. The stdlib default is HTTP/1.0, which never chunks, so a stream would end only when the connection closed, and every POST would open a new SSH channel through the tunnel.
  - The NDJSON stream is chunked by hand, with `Content-Type: application/x-ndjson` and `nosniff`.
  - POST connections are kept alive.
  - While paused, a heartbeat line goes out every 1-2 s. It also drives disconnect detection (section 8.6).
  - The client uses `fetch()` with `Authorization: Bearer <session token>`.
  - `EventSource` is not used, because it cannot send headers.
  - *Measured* through WebKit in the uisnap harness: about 10-byte chunks arrived one by one at 100 ms pacing.
- **Latency.** Click to acknowledgement is the actor queue plus about 13 ms of journal fsync. *Estimate:* under about 30 ms on the lab and under about 50 ms through the LAN tunnel.
- **Money in the client.** The client does no float arithmetic on money. It formats integer pence and hundredths from the engine.

### 8.6 How Yu sees it (R-2)

**Every command Yu runs uses the release copy.** That is `~/.local/share/betangel-suite/app/current/bin/suite`, with a staged alias `suite` for Yu's shell.

- **How a release is made.**
  - A release is a `git archive` of a merge commit on main, named by its full SHA, not a tag, and installed by one command, `bin/suite release <merge-sha>`, after review (Nuance, PR #1 review).
  - That command refuses a dirty tree, or a commit that is not on the first-parent line of `refs/remotes/origin/main` (below), after the operator's `git fetch`: whoever runs the command fetches first, and the suite never fetches. It writes `RELEASE.json` (commit, tree hash, file sha256s) and makes the copy read-only. `release.py` is on phase0/viewing, where round 5 moved its check from `refs/heads/main` to `refs/remotes/origin/main` (Nuance's PR #1 re-review, finding 13; 83b6eb3); the first-parent check is to be added there, with tests.
  - **Ancestry and the first-parent line, both** (Nuance's answer of 2026-10-18 to lab-Claude's round-5 question, which lab-Claude adopts). After the operator's fetch, `git merge-base --is-ancestor <sha> refs/remotes/origin/main` must succeed, and `git rev-list --first-parent refs/remotes/origin/main` must list `<sha>`, so a commit inside a merged branch is refused. In Nuance's words: "Ancestry alone admits side-branch commits inside a merge, which were never a reviewed main tip." Nuance calls first-parent membership the closest proxy, from history alone, for main having pointed at the commit: "A fresh clone has no reflog." The headless gate below uses the same two checks.
- **What a working checkout can do.** An engine whose code is not a release copy with a matching `RELEASE.json` runs in **synthetic mode** only: `serve`, `open` and `ssh-session` refuse every non-synthetic data root there.
- **Headless counts-only commands** (`selfcheck`, `catalogue`, `diagnose`, `ledger-summary`) read real roots only from reviewed code, because their output goes into an agent's context (Nuance, PR #1 review, item 4). The route is the reviewed-code gate (lab-Claude's decision of 2026-10-17; Astra's PR #1 review, item 10, and Nuance's PR #1 re-review, finding 13). Reviewed code is either:
  - a release copy, with `RELEASE.json` naming its merge SHA; or
  - a clean checkout of a merge commit on the first-parent line of `refs/remotes/origin/main`, after the operator's `git fetch`, by the same two checks (ancestry and first-parent membership) and a third: the commit must be a merge commit, so `<sha>^2` must name a commit. The third check is lab-Claude's decision of 2026-10-19 and part of the gate's spec for when it is built (1a): every PR lands with `gh pr merge --merge` (section 3.9), so each reviewed main tip is a merge commit, and releases already come from merge commits (above). The ref is named in full: a local `main` can hold lab-Claude's own merges before review, and a tag named `main` shadows the branch (Nuance's probe in a throwaway repository: an unreviewed local commit passed against `refs/heads/main` and was refused against `refs/remotes/origin/main`).

  It stops accidents, not same-uid rewrites: a process running as `user` can rewrite a checkout, its refs or a release copy (section 9.4). Tests plant leaks: a headless command with a planted leak (`os.write(1, ...)`, a child process, an id-shaped integer), run from a dirty checkout, from a commit that `refs/remotes/origin/main` does not contain, from a commit inside a branch merged into it (off its first-parent line), or from a commit on that line with no second parent, is refused before any real root is read.
  - A filter on `sys.stdout` would not be enough: it misses `os.write(1, ...)` and child processes, and a grammar of bare integers passes ids and prices.
  - A reviewed filter at the file-descriptor level (stdout and stderr `dup2`'d to pipes, passing only codes and registered `key=value` pairs) was the other route offered. It is recorded only as a later option, not the MVP's route, so I-16, I-18 and the 1a exit now agree.
- **Why.** Yu's viewing of licensed data never runs unreviewed code. `session.json` records the release tree hash.
- **Iteration.** In Phase 1a, Yu can look at work in progress in synthetic mode.

1. **The lab's own screen** (no change needed; available from Phase 0).
   - Yu runs `suite open` and opens the result in a Safari Private window.
   - The engine starts, and during its startup phase calls `/usr/bin/open` with `http://127.0.0.1:8765/#c=<bootstrap code>`. The URL is never printed.
   - If an engine is already running, `open` attaches through the control socket, gets a fresh code and opens it.
   - The page POSTs the code to `/api/v1/bootstrap`, gets a session token, keeps it in JS memory only, and strips the fragment with `history.replaceState`.
   - Yu should sign out of historicdata.betfair.com in the lab's Safari, and delete saved betfair.com passwords and betfair.com site data there, now rather than after the downloads. The lab should hold no Betfair session (mailbox 08:57Z, B4, which asks for both; Nuance, PR #1 review). Agreed by Yu on 2026-10-17, for Yu to do by hand, and done: Yu's words of 2026-10-18, as relayed by Nuance, are "Pw deleted too", which Nuance reads as Yu having done the clean-up (Q-Y11; section 2.2.1; confirmed by Yu in Yu's own hand on 2026-10-19). Agents never touch browser data or passwords.
2. **From the Air: recommended, needs Yu's approval (R-2).** A forced-command, tunnel-only SSH key, plus an sshd drop-in.
   - **Staging.** Lab-Claude stages `tools/stage/suite-viewer-setup.sh` (lab side) and the Air `~/.ssh/config` snippet, and never runs either.
     - Yu generates the key on the Air, with a passphrase. Only the public key moves.
     - **Yu runs the lab script**, not Nuance or lab-Claude. It needs sudo for the drop-in.
     - Yu updates the CLAUDE.md line that says "authorized_keys holds only the MacBook Air key".
   - **The sshd drop-in** (`/etc/ssh/sshd_config.d/200-lab.conf`, checked with `sudo /usr/sbin/sshd -t`):
     ```
     AllowTcpForwarding local
     AllowStreamLocalForwarding no
     PermitListen none
     ClientAliveInterval 15
     ClientAliveCountMax 4
     ```
     - **Why it is needed.** OpenSSH's `remote_open_match()` accepts any Unix-socket listen path, so `permitlisten` cannot close `-R` to a Unix socket. Without the drop-in, `restrict,port-forwarding,permitopen=...` would still allow `-R` TCP listeners on any lab port and `-R` Unix-socket listeners at any writable path. That would be a lab-to-Air reverse channel, or a socket planted in a future 0700 run dir.
     - **Nothing is lost**, because the only other key already has `no-port-forwarding`.
     - **`ClientAlive*`** makes sshd notice a dead Air connection within about a minute while the connection is idle, but not while the stream flows (see "The bound for a silent disconnect" below). It applies to every SSH session, which is why it is in the same approval.
     - `PermitOpen 127.0.0.1:8765` may optionally be set globally as well.
   - **The lab's `authorized_keys` line:**
     ```
     from="192.168.50.*",restrict,port-forwarding,permitopen="127.0.0.1:8765",command="/Users/user/.local/share/betangel-suite/app/current/bin/suite ssh-session" ssh-ed25519 AAAA... yu-air-suite-viewer
     ```
   - **The Air's `~/.ssh/config`:**
     ```
     Host lab-suite
       HostName 192.168.50.88
       User user
       AddressFamily inet
       IdentityFile ~/.ssh/id_ed25519_lab_suite
       IdentitiesOnly yes
       AddKeysToAgent no
       UseKeychain no
       LocalForward 127.0.0.1:8765 127.0.0.1:8765
       ExitOnForwardFailure yes
       RequestTTY no
       ServerAliveInterval 30
       StrictHostKeyChecking yes
     ```
     The passphrase, together with `AddKeysToAgent no` and `UseKeychain no`, means no other process on the Air can use the key silently. That includes Nuance, which runs as the same user.
   - **Use.** Yu types `ssh lab-suite` on the Air. Do **not** use `-N`: a forced command runs only when a session channel is opened.
     - `bin/suite` checks `SSH_CONNECTION` and `SSH_ORIGINAL_COMMAND` before `env -i` (section 3.6).
     - It prints a single-use URL (`http://127.0.0.1:8765/#c=<code>`; code valid for 120 s) to that session's stdout only.
     - Yu pastes the URL into a Safari Private window (Cmd-click would open a normal window).
     - Pressing Enter in the ssh window prints a fresh code, for example after a page reload.
   - **Session lifetime: pause unless watched** (an MVP invariant, I-19):
     - The actor auto-pauses when the controller tab's stream drops or the page reports `visibilitychange` hidden.
     - The engine writes a heartbeat to the ssh-session's stdout every 15 s. A failed write means pause.
     - On stdin EOF, `ssh-session` pauses and keeps the session for `watch_grace_s` (default 10 min) instead of stopping.
     - A new `ssh lab-suite` (or `suite open`) during that time **takes over** through the control socket. The engine pauses, journals a note, invalidates the old session token and issues a fresh code. It is not refused.
     - Only when the grace period expires with nobody watching is the session marked `abandoned` and the engine stopped.
     - A maximum session time (default 4 h) still applies; the session then ends as `max_session`.
     - **The bound for a silent disconnect** (the lid closed or Wi-Fi gone, with no clean close; Nuance, PR #1 review, item 8). Through `ssh -L`, the lab's sshd keeps reading the stream into a 2 MiB window, so the engine's writes do not fail. In Nuance's probes, a loopback sshd sent no keepalive while a 17 KB/s stream flowed and timed out after about 135 s; on a tip copy, a peer that reads and never closes kept the clock running for all 40 s of the probe. So today a silent disconnect pauses only within about 3 min (longer while paused; *inference*).
     - **Owed before Phase 1b, with a test:** the actor pauses with reason `not_watched` after about 5 s with no request from the playing controller.
   - **What the key can and cannot do.** Lab-Claude stages an Air-side self-test, which Yu or Nuance runs right after installing the key. It attempts each of the following and reports what is refused:
     - any requested command (the launcher runs instead);
     - `-L` to any other host or port;
     - `-L` to a Unix socket;
     - `-W host:22`;
     - `-R 127.0.0.1:N:...`;
     - `-R /tmp/x.sock:...`;
     - a PTY.
   - The existing Air agent key keeps `no-port-forwarding` and is never used for Yu's UI. Removing the viewer line revokes access.
3. **Alternative: macOS Screen Sharing** on the lab, which Yu turns on in System Settings. It is broader: full desktop control from the LAN.
4. **Not recommended:**
   - binding the engine to the LAN (Bet Angel's port-9000 anti-pattern);
   - a VPN or exit node (lab rule 5);
   - copying licensed data to the Air;
   - running the MVP engine on the Air next to the Betfair credentials.

**The trust boundary.** The tunnel makes lab-served JavaScript run in Yu's Air browser. That JS is written by lab-Claude and is replaceable by any lab process running as `user`; `chmod a-w` does not stop the owner. This is the only lab-to-Air code path.

A buggy or tampered page could show a fake Betfair login and send what Yu types to the lab. The CSP cannot prevent that, because the lab sets it. Hence:

- the suite UI never has credential fields, so any login prompt in it is an attack;
- use a Private window on both machines (Q-Y11, Yu's answer of 2026-10-17);
- during R-2 the only suite listener on the Air is the `ssh -L` forward on `127.0.0.1:8765` (or on the port section 9.2, item 2 allows if 8765 is taken there), behind the token and the Host and Origin checks; L1 removes it (Nuance's PR #1 re-review, finding 7, which corrects this line's earlier "(Unix sockets only)": Nuance's offline `ssh -G` of the staged config gave `localforward [127.0.0.1]:8765 [127.0.0.1]:8765` and `gatewayports no`). Other Air services listen on TCP loopback too: Nuance counted 10 or more TCP loopback listeners on 2026-10-16 (PR #1 review, item 7). Because the lab sets the CSP, a tampered page at `127.0.0.1:8765` can send blind requests and WebSocket handshakes to any Air loopback port, and they pass localhost Origin allowlists. None is exploitable now; one with its login stopped would be, which is Yu's to fix in that service's own repo. **Two checks, both run by Nuance on the Air; neither clears the residual** (Nuance's N-r5-002-1 and N-r5-002-2, in Nuance's review of PR #5 at 52a9edc, adapted to this section; they answer item 2 of Astra's review of PR #2 at 4fa5835, which found that round 5 had dropped the inspection of the Air's other loopback listeners). (1) **The port check, a gate before each `ssh lab-suite`.** It began as Nuance's PR #1 review, item 7; lab-Claude proposed in round 5 that Nuance run it on the Air; its port-scoped pass test is in Nuance's words of 2026-10-18 (Nuance's mailbox note): "Before the forward, nothing listens on port 8765 at any address." "After it, there is exactly one listener: `ssh` on `127.0.0.1:8765`, with none on `[::1]` or `*`." The gate is `netstat -anv -p tcp | awk '$6=="LISTEN" && $4 ~ /\.8765$/'` on the Air, or the same for the other port if section 9.2, item 2's alternative is in use. (Run without root, `lsof` sees only the caller's own sockets, so it cannot show that nothing listens at any address.) (2) **A loopback inventory: a review, not a must-be-empty test,** run before the first R-2 viewing and whenever the list changes. `netstat -anv -p tcp` lists every TCP listener on 127.0.0.1, ::1 or a wildcard address, from every owner. Nuance records process, address and port on the Air, not in the repo. A listener that a blind request or WebSocket handshake could drive without authentication goes to Yu before viewing. The residual stays open until a reviewed deny-all content rule exists: L1's, which RS-1a cancelled, or a replacement. Here the residual is the Air's other loopback services, and RS-1a is proposal 003's (section 2.2.1). This item is the full text; section 9.4's row, section 16's risk row and Appendix C item 7 only summarise it;
- the later native shell uses `WKWebsiteDataStore.nonPersistent()` and no `console.log` of data.

**What reaches the Air.** Replayed prices appear on the Air's screen and in the browser's memory. In a normal window, Safari History, iCloud History and iCloud Tabs would also sync the URL and `document.title`. Safari may also keep page thumbnails (*inference*). The Private window, the static title and the single-use code address this. It is still personal internal use; the question was put to Yu anyway, and Yu answered it with R-2 (Q-Y2).

**Screen capture on the Air** (Nuance, PR #1 review, item 6). R-2 puts real races, and a live bootstrap code, on the Air's screen.

- A Claude Code shell on the Air passes `CGPreflightScreenCaptureAccess()` (Nuance checked the preflight only and took no capture), so `screencapture` would get the whole display with no prompt. Computer use is a second path.
- Rule 5 forbids capture while a suite page or an `ssh lab-suite` window is open. That is conduct only, and sessions in other repos on the Air never read this repo's AGENTS.md.
- A line in the Air's CLAUDE.md saying the same: approved by Yu on 2026-10-17 (Q-Y10; section 2.2.1), and in. Nuance confirmed on 2026-10-17 (08:48Z) that it is in the "Betangel suite" section of the Air's `~/.claude/CLAUDE.md`, and reports that Yu confirmed it to Nuance directly (Nuance's PR #1 re-review, finding 4). It is a CLAUDE.md rule for Claude Code sessions on the Air; for Astra and other tools it is conduct only. Q-Y10 covers the Air before its first real race.

### 8.7 Feedback and problem reports

- **Report a problem.** A `report_problem` command (a button, with an optional fixed category) writes `reports/<session_id>-<n>.json` under the suite root. It contains:
  - the session id and attempt;
  - the virtual pt as an offset from the scheduled off;
  - the last N command codes;
  - counters, `invalid_reason` codes and frame timings.
  
  It contains no names, prices or market ids.
- **Diagnose.** `bin/suite diagnose <report>` replays that session's member headless to the reported offset, reads the existing journal, and prints codes and timings only. It does not re-execute orders on real data (R-6).
- **Real values: not available without Betfair's specific written agreement naming the provider** (Nuance, PR #1 review, item 2; Q-Y9, confirmed by Yu on 2026-10-17, section 2.2.1). When structure is not enough, Yu describes the shape, or lab-Claude adds a code-only check to `diagnose` that prints codes. Agents never read real values.
  - **Why Yu's OK alone is not enough.** It would put named real fields into a hosted model context, which counts as an upload (rule 5, section 3.9). The Betfair Historical Data terms' "No onward distribution" clause prohibits "the use of the Historical Betfair Data by, another organization or individual" unless "a specific agreement in writing with Betfair exists", and Betfair has not ruled on model providers (the clause as quoted in proposal 001, sections 5.1-5.2; proposal 001 is PR #3, not merged).
  - So real fields reach a model provider only with Betfair's specific written agreement naming that provider, plus Yu's OK each time in Yu's direct channel (section 3.9), scoped to one problem report and named fields. Yu's answer would be recorded in the report folder, and nothing beyond that scope read. Until such an agreement exists, exceptions are not available.
  - No "same-shape" fixture is ever derived from a real report: it would still be a licensed derivative (proposal 001, section 3.2; PR #3, not merged).
- **Acceptance.** Yu works through each phase's checklist in that channel. Relays from Nuance are context, not acceptance.

---

## 9. Local API and security

### 9.1 Transport and the closed route table

- **Bind.** A `ThreadingHTTPServer` subclass binds `127.0.0.1:<port>` only and asserts `getsockname()` after the bind. There is no IPv6 wildcard, no `SO_REUSEPORT`, and no fallback port: a failed bind aborts.
- **Overrides.**
  - `server_bind` skips `socket.getfqdn()` (`http.server.HTTPServer.server_bind` calls it), so no name lookup ever runs.
  - `log_message` logs codes only: no paths, query strings or tokens.
  - `handle_error` (which by default prints a full traceback, socketserver.py:372-383), `sys.excepthook` and `threading.excepthook` print only the exception class and a code. In this phase no traceback is written anywhere (`errors.install_excepthooks`: "Phase 0 writes full tracebacks nowhere"; Astra's PR #1 review, item 12). When full tracebacks are kept, later, they go only to 0600 files under the suite root's `private/`, which agents never read.
  - `send_error` and `end_headers` make even pre-routing errors (400, 414, 501) return code-only JSON with the section 9.3 headers.
- **Protocol.** HTTP/1.1, with a hand-chunked stream (section 8.5).
- **Routes.** A closed table, asserted by an exact-equality test:

| Method | Path | Purpose | Side effects |
|---|---|---|---|
| GET | `/` and the exact names in `ui/manifest.json` | static UI | none |
| POST | `/api/v1/bootstrap` | exchange a single-use code for a session token | invalidates the code |
| GET | `/api/v1/stream` | NDJSON frames for this tab | none |
| POST | `/api/v1/query` | read-only queries: catalogue, session, journal view, green-up preview | none |
| POST | `/api/v1/command` | commands from a closed enum | yes |

- **Command enum:** `open_market`, `play`, `pause`, `set_speed`, `seek`, `jump`, `step`, `subscribe`, `claim_control`, `place`, `cancel`, `cancel_side`, `cancel_all`, `stop`, `resume`, `void_and_rewind`, `report_problem`, `set_prefs`, `export_csv`. Exploration mode adds `replace`. A test asserts that no route or command name contains `live`, `account`, `funds`, `login`, `kill`, `upload` or `share`.
- **Static files** are mapped from the manifest by exact name, never joined from the request path, and there is no directory listing.
- **Control socket.** `run/control.sock` (0600, in the 0700 run dir) accepts only `attach`, `new_code`, `pause` and `stop`, from the same uid (checked with `getpeereid`). Its clients reach it under I-3's one exception, which comes with them (section 10).
  - `new_code` mints a fresh bootstrap code for whichever same-uid process asks, silently: nothing is printed to Yu or opened (Nuance, PR #1 review). Agents never send `attach` or `new_code` to the real control socket under `~/.local/state/betangel-suite/run/` (rule 6); tests send them only to engines in temporary HOMEs. That is conduct only (section 9.4).

### 9.2 Authentication and request checks

1. **Bootstrap code and session token.**
   - Each `open`, `ssh-session`, takeover or Enter press issues a **single-use bootstrap code** (`secrets.token_urlsafe(16)`, valid for 120 s, invalidated on first use).
   - The page exchanges the code by `POST /api/v1/bootstrap` for a **session token** (`secrets.token_urlsafe(32)`).
   - The server keeps the token in memory only, never on disk. The page keeps it in JS memory only, never in `sessionStorage` or `localStorage`. A reload needs a new code.
   - So a copy of the URL in `ps` (the `/usr/bin/open` argv), browser history, iCloud or Terminal saved state is dead once the page has redeemed the code or 120 s have passed, whichever comes first. Until then it is live (Astra's PR #1 review, item 12).
   - Both values go through `secret.register`, so any journal or receipt write that contains one is refused (`assert_clean`; journal.py:296; receipts.py:185, :214).
   - The token is required as `Authorization: Bearer` on every `/api/` request except `bootstrap`, the stream included, and compared with `hmac.compare_digest`. A missing or wrong token gets 401.
   - There are no cookies, because cookies on `127.0.0.1` are shared across ports, and no query-string tokens.
   - A takeover invalidates the previous token.
2. **Host.** The host name must be exactly `127.0.0.1` or `localhost`, with a numeric port; otherwise 421. This defeats DNS rebinding, and still allows another local port on the Air if 8765 is taken there.
3. **Origin.** It is required on POST and must equal `"http://" + Host`; otherwise 403. If present on the stream GET, it must also match.
4. **POSTs.** POST only, with `Content-Type: application/json`; anything else gets 415. Simple cross-site form, text or `no-cors` POSTs therefore fail, and a JSON POST needs a preflight that is never answered.
5. **No CORS.** No `Access-Control-*` header on any response, and `OPTIONS` gets 405.
6. **Bodies.** Parsed with `receipts.strict_json_loads` (receipts.py:247: duplicate keys and NaN are refused), against exact-key schemas. The limit is 64 KB, with 413 above it, plus per-route rate limits.
7. **Idempotency.** Every command carries a client nonce. A replayed nonce returns the first result and does nothing new. `place` and `cancel` append with `expect_head` (section 7.3).
8. **One controller tab.** A second tab is read-only until it sends `claim_control`.
9. **Errors are codes only.** No tracebacks, request bodies, data rows or identifiers. Upstream exceptions are mapped at the `rx.py` boundary:
   - The caught exceptions are `IndexProblem`, `ArchiveProblem`, `PathDenied`, `ValueError` and `JournalError`. These embed member paths, which contain real event and market ids: for example `where = f"raw:{member['path']}"` (market_index.py:726) and `_label(name)` (archive.py:298, :348, :815).
   - The boundary keeps only the reason after the last colon, from a closed enum. Any identifier is replaced with a salted hash. The salt is per install, in a 0600 file at `~/.local/state/betangel-suite/install-salt`, not under the suite root (AGENTS.md adaptation B): it is made once, at first provisioning (below), and only the engine may write the suite root.
   - **The hashes are pseudonymous, not anonymous** (Nuance, PR #1 review, item 3, and PR #2 review, item 14, which estimates about 427k HMACs a second per core). The hashed labels follow the public member layout (archive.py:245-264), so a ref for an event file reverses by enumeration in about 13 minutes on one core. So the salt is on rule 5's never-read list, with its own Read deny (Q-Y9).
   - **Made once; a lost salt is refused, not regenerated** (lab-Claude's decision of 2026-10-17, as Nuance recommends; Nuance's PR #1 re-review, finding 2, and PR #2 re-review, F12; Astra's PR #1 review, item 9). Until round 5 the code made fresh bytes whenever the file was missing, so a lost salt would have split every hash silently: in Nuance's probe, one label hashed differently in two processes either side of a lost salt. Now:
     - at first provisioning the salt is written and fsynced, with its directory, and only then is a separate marker written, `~/.local/state/betangel-suite/salt-provisioned` (0600). It holds nothing secret and is not named `install-salt*`;
     - once that marker exists, a missing, unreadable or wrong-length salt is refused with `salt_missing` (fail closed), and no new salt is made;
     - restoring a lost salt is Yu's; no agent reads, copies or restores it. Losing the salt and the marker together looks like a fresh install, which the marker cannot catch.

     A salt made before the marker existed gets its marker the first time it is read; until then, a lost salt is still made again. The code and its tests, in temporary HOMEs, are on this branch (8288c76).
   - **The move is withdrawn.** Lab-Claude had proposed moving the file into `~/betangel-data/suite.noindex/`, and asked Nuance on 2026-10-17 what "Move the salt, never regenerate it" (PR #1 review, item 3) meant. Nuance's answer to lab-Claude's question 4 of 2026-10-17 (PR #2 re-review): "I meant the file, conditionally, and worded it badly. I recommend not moving it: Yu's deny already covers it as well as a `~/betangel-data` deny would, so a move adds no protection and several costs". Lab-Claude accepts it: the salt stays where it is, with its own Read deny.
   
   This applies to stdout, stderr, `logs/` and HTTP alike.

### 9.3 Headers on every response

- `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`
- `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`
- `Cache-Control: no-store`
- The stream also sends `Content-Type: application/x-ndjson`.

These headers apply to error responses too (section 9.1).

### 9.4 Threat model

| Threat | Mitigation | Residual |
|---|---|---|
| A hostile web page in Yu's browser (CSRF, DNS rebinding, cross-origin reads, clickjacking) | Bearer token in a header, single-use bootstrap code, the Host and Origin checks, JSON-only POST, no CORS, CSP and frame-ancestors, no cookies | None known. |
| Devices on the home LAN | Loopback-only bind; the viewer key is least-privilege (forced command, one `permitopen`, `from=192.168.50.*`); the sshd drop-in closes `-R` and Unix-socket forwarding | Depends on Yu installing the drop-in with the key; the Air-side self-test confirms it. |
| **Lab-served JS running in Yu's Air browser** (the only lab-to-Air code path) | No credential fields (any login prompt is an attack); a Private window (Q-Y11, Yu's answer of 2026-10-17); no suite listener on the Air but the `ssh -L` forward during R-2, behind the token and the Host and Origin checks; reviewed release copies only | A tampered page can still show anything on screen; Yu's rule is never to type credentials into it. It can also send blind requests and WebSocket handshakes to other Air loopback services. Summary of 8.6, which has the full text: two checks, both run by Nuance on the Air, a port gate before each `ssh lab-suite` and a loopback inventory that is reviewed, not required to be empty; neither clears the residual, which stays open until a reviewed deny-all content rule exists. |
| **Same-uid processes, including agents, holding or minting the token** (lab-Claude locally; Nuance through Nuance's full-shell key) | Single-use codes; token in memory only and registered with `secret`; `open` and `--print-url` refused over SSH; the agent-conduct rule (agents never run `open`, `ssh-session` or `--print-url`, never send `attach` or `new_code` to the real control socket, and never POST commands on a real-data engine); the passphrase-protected viewer key | Not preventable against a determined same-uid process, as in the repo's own threat model (presence.py:1-11). I-8 and I-16 are code-path properties, not proof of a human. |
| **Screen capture on the Air** while a suite page shows a real race or a bootstrap code (an agent's `screencapture` passes the preflight with no prompt; computer use) | Rule 5: no capture while a suite page or an `ssh lab-suite` window is open; Q-Y10 covers the Air before its first real race (section 8.6) | Sessions in other repos never read this repo's AGENTS.md. A line in the Air's CLAUDE.md: approved by Yu on 2026-10-17 (Q-Y10), and in (Nuance confirmed it on 2026-10-17). It is a CLAUDE.md rule for Claude Code sessions on the Air; for Astra and other tools it is conduct only. |
| Browser extensions reading licensed data | A Private window (Q-Y11) | An extension Yu has allowed in Private Browsing could still read the page (*inference*). Q-Y11, answered by Yu on 2026-10-17: a Private window, not a profile without extensions. |
| Supply chain | No third-party Python or JS. A pinned, hash-checked upstream with an import-origin assertion. `-S` drops site-packages. | Homebrew python@3.13 itself. |
| Upstream drift widening imports or changing semantics | The import-closure test, the contract test, reviewed pin bumps | It still blocks work when it breaks, but loudly. |
| Accidental real betting | No live code in this repo, no credential path, FORBID_NETWORK, the audit hook with no off-switch, boundary tests | None in the MVP. |
| Crafted or corrupt data files | Hash of the exact bytes parsed, decompressed size checked against the manifest, tight bounded decompression, the strict reader, `book.py`'s own refusals | — |
| Licensed-data leakage (git, logs, error text, screenshots, model context, browser history, Spotlight, crash reports, SQLite temp files, exports) | Hygiene scanner (bounded pattern detection) and its four git hooks (pre-commit, pre-merge-commit, commit-msg, pre-push; on the lab only pre-commit is live, section 5.6); provenance review of each PR; synthetic-only fixtures and uisnap screenshots; error mapping; aggregate-only diagnostics; agents never read, search or list `~/betangel-data` or the install salt (rule 5); `.noindex`; `TMPDIR`/`SQLITE_TMPDIR` and `temp_store=MEMORY`; no-store; exports under `~/betangel-data` only | Human error, covered by review. Until the other three hooks are live on the lab, no hook scans a commit message or a push there: the manual scans before a push are conduct (section 5.6; Nuance's PR #2 re-review, F9). The lab's home is not a git worktree, so a search from `~` walks into `~/betangel-data`, whose `raw/` paths carry market ids (Nuance, PR #1 review, item 3). Lab-Claude's file tools have deny rules for `~/betangel-data` and the install salt, which Yu approved on 2026-10-16 (Q-Y9): Read and Edit are denied; Grep and Glob are unverified; Bash is conduct only. On the lab, `claude --version` is 2.1.301. Lab-Claude's main session has no Grep or Glob tool, so its searches go through Bash, which the deny rules do not cover. Whether a subagent's Grep or Glob honours the Read deny is unverified: from the Air's 2.1.302 binary, Nuance found that a Read deny becomes ripgrep `--iglob !` exclusions, so a search from `~` silently skips the subtree, with no refusal (Nuance's PR #1 re-review, finding 6). For Nuance's SSH shell and Astra, rule 5 is conduct only. Analytics and Spotlight Privacy are Yu's decisions (Q-Y14, Q-Y15). |
| Interfering with Nuance's runs | No engine or real-data command starts while the run marker exists, and one already running drains; the real-data lock Nuance's wrapper waits on; no automatic catalogue rebuilds | Until Nuance's agreement of the marker is recorded at the merge-candidate SHA, lab-Claude also runs no real-data command while a run is announced, and no engine command runs on the lab with the real HOME (section 6.8). |
| Agent or scope drift toward live features or automation | The suite's AGENTS.md, the closed route test, the OperatorClick test, synthetic-only `TestOrder`, the proposal process | The rule against auto-keypresses and timed actions lives in `ui/` JavaScript, which the server cannot check (I-8). Since Yu narrowed UI-only on 2026-10-17 (section 3.9), changes to `ui/`'s order-sending paths go to Astra, and to Nuance as well for paper keys. Whether a `ui/` diff touches those paths is judged by reading it, and until the node tests exist (owed before 1b; section 8.3) no test catches a repeated key or a timer that reaches an order command (Nuance's PR #1 re-review, finding 3). |

---

## 10. Safety invariants and how tests prove them

| ID | Invariant | Mechanism | Test |
|---|---|---|---|
| I-1 | No credential code path | Only `rx.py` imports betangel_research, and only from the allowlist | An AST test: `rx.py` is the sole importer, and imports only allowlisted names. A fresh-subprocess import of the full engine checks the closure: the 25 modules, and none of gateway, cli, auth, credentials, transport, api, esa, recorder, killswitch, arming, presence, reconcile, risk or capability. A static scan of **suite sources only** looks for `security` CLI or Keychain strings, Betfair hosts, `placeOrders`, `cancelOrders`, `replaceOrders`, `updateOrders` and `HeartbeatAPING` (the test builds these names by concatenation). The deps closure is checked separately, by its module set and by the absence of gateway order-method literals in those 25 modules. `constants.py:14-32` and `config.py:35` legitimately hold hosts and `"keychain"`. |
| I-2 | FORBID_NETWORK is always on | The launcher sets it. `guard.py` refuses unless `paths.network_forbidden()` is true and no other `BETFAIR*` or `BETANGEL_BETFAIR_*` variable is set. `guard.py` has no off-switch. | Engine start without it is refused. A stray variable is refused. An AST test finds no environment or config read that disables the guard. |
| I-3 | No outbound network, no name lookups | The PEP 578 audit hook (irrevocable), installed before any upstream import, refuses `socket.connect`, `connect_ex`, `sendto`, `getaddrinfo`, `gethostbyname` and `gethostbyaddr`, in every mode.<br>**The control-client exception** (Astra's PR #1 review, item 8). `stop`, and the takeovers by `open` and `ssh-session`, connect to the control socket (sections 3.1 and 9.1), which this row would otherwise refuse. The one exception is a connect to the control socket's exact path in the 0700 run dir, permitted before `seal()`; TCP connects and every other address stay refused. It ships only with the control socket's clients and their tests (`permit_unix_connect`, built on phase0/http in 29d551e). | `socket.create_connection(("192.0.2.1", 443))` (TEST-NET-1) raises before any packet. `getaddrinfo("example.com", 443)` raises. A second hook cannot remove the first. With the exception (phase0/http): a Unix connect to a path not permitted before `seal()` raises, and so does a TCP connect to `127.0.0.1`. |
| I-4 | Loopback only | The hook allows `socket.bind` only to `("127.0.0.1", port)` and to the control socket path in the 0700 run dir, matched by its exact text, with no NUL in it (the kernel ends the socket name at the first NUL), while the run dir still resolves where it did at `arm()` and the socket path is not itself a link (bind follows a dangling one and creates the socket at its target). The hook allows `listen()` only on an AF_INET socket bound to 127.0.0.1 with a non-zero port (a permitted port-0 bind has its port by then), or on an AF_UNIX socket bound to a name (`listen_refused`; Nuance's PR #2 review, item 4; 01f6201). CPython raises no listen event, and `listen()` on an unbound AF_INET socket binds 0.0.0.0. So at the first `socket.__new__` event the hook puts a wrapper that raises `socket.listen` on `socket.socket.listen`. `arm()` does this at once if `socket` is already loaded, and never imports it. AF_INET6 is refused. So is making a socket whose class would not call the wrapper: a bare `_socket.socket`, or a subclass with its own `listen`. `arm()` refuses (`call_replaced_early`) if `socket.socket` already has a `listen` of its own. `getsockname` is asserted. | Binding `0.0.0.0`, the wrong port or another Unix path raises, and so does a permitted Unix path that is a dangling link. A Unix path with a NUL in it is never permitted. The server's address is `127.0.0.1`. A control-socket peer of another uid is refused. `listen()` on unbound AF_INET, AF_INET6 and AF_UNIX sockets raises `listen_refused`. These are tested on SOCK_DGRAM sockets, which never listen, so a miss cannot listen on 0.0.0.0. A port-0 loopback bind listens, before and after `seal()`. |
| I-5 | No subprocess after startup | In engine mode the hook's **startup phase** allows one argv shape, a shape it accepts, not a single use (Astra's PR #1 review, item 3): `/usr/bin/open http://127.0.0.1:<port>/#c=...`.<br>The git probe `git -C <abs dir under the suite roots> rev-parse --is-inside-work-tree` (paths.py:149, used by `validate_config` and `StatePaths`) was allowed until round 6 and is refused now: no Phase 0 path runs it, and the guard never judged its environment, so with `DEVELOPER_DIR` set it ran a planted `xcrun`, and with `GIT_TRACE` it wrote a file outside the roots (Nuance's review of PR #2 at 4fa5835, N5-1). The gap that stays: in engine mode the guard judges a child's argv, not its environment, and `os.putenv` is refused only for the pinned and stray keys. If Phase 1b needs the probe, it comes back with an exact environment, `env=None` and any other `putenv` refused in engine mode, and an engine-mode test like the test runner's `DEVELOPER_DIR` test.<br>In vendor mode it allows instead exactly the five git argvs of `tools/vendor_research.py` (`cat-file -e` and `merge-base --is-ancestor` in the clone, then `clone`, `checkout` and `remote remove`), each with exactly `guard.VENDOR_GIT_ENV` plus HOME (Nuance's PR #2 review, item 10, and Q-N2; 816e832, 1d23fdc).<br>Then `seal()`. After sealing it refuses `subprocess.Popen` and `os.posix_spawn`. In every phase and mode it refuses:<br>- `os.system`, `os.exec*`, `os.spawn*`, `os.fork` and `os.forkpty`;<br>- a direct `_posixsubprocess.fork_exec`, which `arm()` wraps so that it raises an event (`subprocess` keeps its own reference to the original); and, once the wrapper is in place, every fresh load of the extension, which would carry the original: an import after it was taken out of `sys.modules`, `importlib.util.module_from_spec`, `_imp.create_dynamic`, and any other name CPython reads as the extension's (`import_refused`; Astra's re-review of PR #2, finding 1; Nuance's PR #2 re-review, F4; ff35218): a dotted name ending in `_posixsubprocess`, a name whose last part spells its `_` as `-` (CPython reads each `-` as `_` when it finds the init function), and on 3.11 one with a NUL after it; the hook refuses every name with a NUL (Astra's review of PR #2 at 4fa5835, item 1);<br>- importing `multiprocessing` (any submodule), `concurrent.futures.process`, `ctypes` or `_ctypes` (`import_refused`), because `_ctypes` reaches libc through `dlsym` and `call_function` with no `dlopen`; `_ctypes` under any such name too; and the modules that run code in a subinterpreter, whose audit hooks are their own (`_interpreters`, `_xxsubinterpreters`, `interpreters`, `concurrent.interpreters`), and CPython's test modules `_testcapi` and `_testinternalcapi` (ff35218);<br>- `ctypes.dlopen`, `ctypes.dlsym` and `ctypes.call_function`, and SQLite extension loading.<br>`arm()` refuses if one of those modules is already loaded, or a second `_posixsubprocess` under any such name (`module_loaded_early`), and unless `subprocess._fork_exec` and `_posixsubprocess.fork_exec` are both the C original (`call_replaced_early`). Threads are unaffected. These are the calls and loads the hook sees or `arm()` wraps, not every route ("The guard's scope", below); test mode differs (below). Two same-process routes stay open: a fresh instance of the built-in `posix` module, whose `mkfifo` and `mknod` are the unwrapped originals, since a built-in module raises no import event (Astra's re-review of PR #2); and an extension refused above that was loaded before `arm()` and then taken out of `sys.modules`, which CPython serves from its cache with no import event when it is single-phase (lab-Claude's probe, round 5). (Nuance's PR #2 review, items 3 and 18; 56a2631, 886d64b. The old text also implied that `os.system`, `os.exec*` and `os.fork` were allowed before `seal()`; they never were.) | Startup succeeds. After sealing, `subprocess.run(["/usr/bin/security", ...])` and `os.system` raise. Any other argv during startup raises. `multiprocessing.Process.start`, `ProcessPoolExecutor.submit` and a direct `fork_exec` are refused before and after `seal()`, and in test and vendor mode, with nothing written outside the roots. `_ctypes.call_function(_ctypes.dlsym(RTLD_DEFAULT, "mkdir"), ...)` is refused. Every fresh-load spelling of `_posixsubprocess`, a dotted `_ctypes` and each subinterpreter module is refused before and after `seal()`, in engine, test and vendor mode, on both interpreters, and `arm()` refuses them loaded early (ff35218); since round 6 also the `-` and NUL spellings of each, in every mode. The git probe is refused in engine mode, with `DEVELOPER_DIR`, `GIT_TRACE` or neither, and nothing is written outside the roots. Threads still work. |
| I-6 | Writes confined | The single writer helper, plus the hook's write guard on `open` (write flags), `os.mkdir`, `os.rename`, `os.remove` and `sqlite3.connect` paths: only the suite state roots, plus a temp root in tests. The write roots differ by mode (below). The suite root under `~/betangel-data` is a write root for the engine only; the test runner, `vendor`, `uisnap` and `stop` never get it (8102f99), so tests, which use temporary HOMEs, cannot reach the real one. `TMPDIR` and `SQLITE_TMPDIR` are the same absolute path with no `.` or `..` component (so it differs from its normalised text at most by a redundant or final `/`), inside the roots both as normalised text and with its links resolved, with no link from its root down to it (8d0955d), and `temp_store=MEMORY` is set.<br>- `arm()` refuses a write root or `TMPDIR` that the file system puts in, around or onto `~/betangel-data` (`root_overlaps_data_home`), and an engine suite root that is not a real directory, or missing, at exactly `realpath(~/betangel-data)/suite.noindex` (`suite_root_misplaced`). It also refuses a placement it cannot judge, because a stat fails for any reason but a missing name (57fc0c9). The hook refuses a symlink, hard link or rename that takes the place of a root, `TMPDIR` or a directory between `TMPDIR` and its root (`root_replace_refused`; 8d0955d for the directories between). Section 3.7; Nuance's PR #2 review, item 1; 62c39c6, 851885a.<br>- `arm()` in every mode, and the writer helper, also refuse a write root or `TMPDIR` in, around or onto `~/.local/state/lab-runs` (`root_overlaps_lab_runs`; Nuance's PR #2 re-review, F5; c3b0c61).<br>- **Reads.** In every mode but engine (test, vendor, uisnap and stop) the hook also refuses reads in `~/betangel-data` (`data_home_read_refused`; lab-Claude's decision to fail closed, on Nuance's answer to lab-Claude's question 2 of 2026-10-17, condition 1; 0a3ed65): an open without a write flag, `os.listdir`, `os.scandir` and `os.chdir`, judged by text, realpath and `(st_dev, st_ino)`, stat calls only. It does not cover `os.open` with a `dir_fd` and a relative path (the open event carries no `dir_fd`, so the name is judged against the cwd, and the outcome depends on the cwd: run from HOME, `shutil.rmtree` of a temporary HOME's `betangel-data/` was refused, so `bin/suite test` runs its tests from its `TMPDIR`; Nuance's review of PR #2 at 4fa5835, N5-3), a descriptor opened before `arm()` or inherited, a hard link made elsewhere, or stat-level calls. Engine mode reads as before: Phase 1a reads the data roots.<br>- **The test runner's children** (Nuance's PR #2 re-review, F2; 96f8a90, 8e751d6). The runner itself is confined as above. Every interpreter child it starts, whatever follows `-I -S -B`, and every `bin/suite` child needs an explicit environment whose HOME, the roots under it and `TMPDIR` keep out of the runner's data home, judged by realpath and identity at spawn (`subprocess_refused`): a child that imports `betangel_suite` arms its own guard from the HOME it is given, and with `env=None` an engine-mode child would have the runner's real suite root. Until lab-Claude's round-5 review only launcher children were checked, which left open the shape F2 reported: `-c` code that arms the guard itself, as every engine-policy test child does (8e751d6). A test child that needs a HOME the runner refuses is started by an unguarded relay (`tests.run_relayed`). What a child does with its environment after it starts, and a child that never imports `betangel_suite`, are unguarded: conduct.<br>- It refuses removing, moving or replacing `run/realdata.lock`, and moving or replacing `run/` itself, which would carry the lock away (`run_lock_protected`; section 6.8; 18de53e, 6aeb1d5). `arm()` refuses a `run/` or lock that is a link (`run_lock_invalid`; b0d5c0d).<br>- `chmod`, `chown`, `utime` and `truncate` on a descriptor are judged by its `F_GETPATH` path, and refused without one (item 17; 59e2f22).<br>- Every SQLite connection is a guard subclass whose `setlimit` refuses `SQLITE_LIMIT_ATTACHED` (`sqlite_limit_refused`), and the hook refuses `sqlite3.connect` events not made by the guard's wrapper: a direct `Connection`, a re-`__init__`, a reference taken before `arm()`, a factory argument (`sqlite_connect_refused`; item 16; 3da0c26).<br>- `temp_store=MEMORY` is read back as 2, and `connect("")` is refused (item 15; 06dba20).<br>Defence in depth, not a sandbox. Same-process code can still call `sqlite3.Connection.setlimit` on a connection directly, set `temp_store` back with a PRAGMA, or call subprocess's private `_fork_exec` or `_socket.socket.listen` directly; neither the suite nor the pinned closure does. `guard.py` lists the other same-uid limits. | A session over fixtures under a temporary HOME-like root writes nothing outside the roots (tree diff). Nothing appears under `/tmp` or `/var/tmp` during a catalogue build or a session. Writes under a data root, or into a `path_guard` denied tree, raise. These are refused too: a root linked into, equal to or containing `~/betangel-data`, as written, through an alias, the firmlink, `/.vol` or another case; `suite.noindex` linked to a data root; a root linked into a data home that cannot be stat()ed when `arm()` runs; a link or rename onto a root, `TMPDIR` or a directory between them, and a `TMPDIR` with a link below its root; a `run/` or lock that is a link; `fchmod` on a read-only descriptor in the data home; `setlimit` on the ATTACH limit, and a re-`__init__` or a direct `Connection`; `connect("")`. A spilled temp table opens no `etilqs` file. Since round 5 these are refused too: a root around, onto or in `lab-runs/`, in every mode (c3b0c61); in test, vendor, uisnap and stop mode, opening, listing, globbing, walking, copying or entering synthetic files in the data home, by every spelling above and through a descriptor from before `arm()`, while engine mode still reads them (0a3ed65); and an interpreter or launcher child of the runner with `env=None`, or with a HOME or `TMPDIR` in or onto the runner's data home, `-c` code that arms engine mode and a launcher after one more interpreter option included (96f8a90, 8e751d6). |
| I-7 | No live route | The closed route table and command enum | Exact-equality tests and the forbidden-name test. |
| I-8 | Orders on real data come only through the operator-click code path. This is a code-path property, not proof of a human (section 7.1). **Proposed** (section 7.1; asked of Nuance and Astra in the round-5 replies; moot under RS-1a of proposal 003 since 2026-10-19, section 2.2.1): cleanup that no request starts only reduces, through `PaperDesk.stop_all(SystemStop)`, which takes no targets and never places. | OperatorClick minted only in request handlers, with a fresh nonce and a valid session token. `TestOrder` and `ReplayedClick` are accepted only in synthetic mode. Proposed: a `SystemStop` minted only in the `run/STOP` poller, the session-end paths and next-start recovery; `.place`, `.cancel` and `.withdraw` never take one; the journal records `system_stop:<reason>`. | An AST test checks construction sites and the callers of `PaperDesk.place`, `.cancel` and `.withdraw`. Nonce replay places nothing. A `TestOrder` on an engine with a real data root is refused. Proposed, owed at 1b: the AST test also finds `SystemStop(` only at its mint sites and `stop_all` its only taker, and `bin/suite stop`, expiry, failure and recovery are tested with no click. |
| I-9 | Licensed data never in git | `.gitignore`, the hygiene scanner, the pre-commit, pre-merge-commit, commit-msg and pre-push hooks, the fixture namespace, and provenance review of each PR. The scanner is bounded pattern detection: a clean scan is not proof that content is synthetic (section 5.6). On the lab only the pre-commit hook is live until the Phase 1a entry gate (section 5.6). | The scanner fails on planted `.bz2`, a large file and a `1.1xxxxxxxx` id, and on binary data past 8 KiB or without a NUL, base64, hex and `\xNN` copies of a bz2 member, a clean-filter attribute, tables split by CR, NEL or LS or behind a BOM, an id in a commit or tag message, and a file only in pushed history (Nuance's PR #2 review, items 5, 19, 20 and 21). After lab-Claude's round-4 review also: a blob or commit hidden by a replace ref or a graft (staged, range and push); pre-push input past 1 MiB (refused); a GIT binary patch, decimal byte lists, `od` output, a bytea literal, base64 of base64 and marker-led dumps of a bz2 member; box-drawing, HTML, LaTeX and fullwidth-bar tables, accented names and names in capitals; unquoted secrets in a file and a message. Near misses stay clean (a sorted price ladder, lists of small counts, marker-led name lists). After the round-4 recheck: lists of full 40- and 64-digit hashes, bare or after a marker, stay clean in a file and a message, while the same shape holding a bz2 member, a zlib or gzip stream or flagged text is still caught (2ae7640); 18 lines of 200 KB each scan within 10 s (805356c). After the round-4 finishing review also: an unclosed literal of escaped quotes on a 200 KB line, within 10 s (1be5dc1); data after one real hash line, and text with one NUL or 0xFF byte, in those layouts (287264a); a PNG or a PDF in those layouts, and raw deflate in more than 64 of those lines (b656145), while lists of 64 hashes stay clean. After the finishing review's recheck also: UTF-16 text, bare or with a BOM, in those layouts (fab0b92); a record of under 96 bytes with one NUL or 0xFF byte, in hex, base64, escapes or a decimal list, and in UTF-16 (53904f8); raw deflate in two runs of 64 of those lines, split by a blank line or a line of words (7126190), while lists of 8 and 32 hashes in one file, and 70 lines of a hash and a subject beside a list of 8, stay clean. After the recheck of 7126190 also, in a file and a message: raw deflate in base64 runs that each decode to a list of 64 or 40 of those lines, in 64 plain lines beside one such run, and in lists of two or four of those lines split by blank lines past 64 lines in all (bfd2f6a), while 64 hashes in lists of two or of four stay clean. After round 5 also: a commit reachable only from a stale tracking ref (77271cd); a commit or tag whose 1 MiB author or tagger line hid its message, refused in `--range` and `--push` (fbd60fa); `--message` through a link, a `..` after a link, a chain of links or a `/.vol` spelling into a data root, refused (35345ba); octal-escaped copies of a bz2 member, as three-digit, shortest-form and shell strings and across lines (58e8426); runner tables with no-break, figure, narrow or ideographic spaces, fullwidth digits and letters, and U+034F or U+FE0F in names and ids, ids so spelt, and tables led by a time, a date or an id (1e39931), while a dated changelog with version numbers stays clean; 29 shapes of 200 KB lines, each within 10 s. Fixture-provenance test. |
| I-10 | Raw data read-only; no ingest or index by the engine | A read-only open. The AST test forbids `ingest_archive` and `index_archive(s)` outside tests. | A synthetic data tree's hash is unchanged after a full session. |
| I-11 | No gated month ever replayed | `month_gate` on path and marketTime at catalogue time and at every open. A `None` month is refused as `month_unknown` first. | Synthetic members dated 2026-01, 2026-09, 2026-10 and 2027-01 are refused with the gate reason. A member with no parseable marketTime is refused as `month_unknown`. Research months are refused while no ruling is set. |
| I-12 | Spoiler-free | Catalogue field allowlist; the tap releases outcome values only at their pt | Planted outcome values never reach SQLite, a frame or the browser before CLOSED. |
| I-13 | Pin integrity, and never the moving clone | Per-file hashes over every `PINNED_FILES` entry, the origin assertion, and the deps directory never on `sys.path` (3f86e34). The pin stays at 76f71dc until a closure module the suite needs, or the month roles, change; Nuance reviews every bump that changes a `PINNED_FILES` entry, and the contract test gates it (Q-N1, Q-N2). The closure finder, the no-link reader, `read_pinned()` and vendor's pre-pass, its identity check against the clone and its `main`-only rule (section 3.5; Nuance's PR #2 review, items 2, 7, 8 and 22, and Q-N2; 1d23fdc, e51b469, e4ddc18, 7357273, 0a1c482, 923c1de, 08af945). | A tampered file in a temp copy gives `pin_mismatch`. `sys.path` never contains `~/betangel-research`. Origin-assertion test. Oracle tests never pass `~/betangel-research` as `repo_root`. A linked `research/` or a hard-linked pinned file gives `pin_mismatch` (both open paths), and a tree spelt with a final `/`, `/.` or `//` is refused (f77cf01). A FIFO never hangs. An unpinned `betangel_research` module is refused by statement, from-import, `import_module`, `__import__` and `find_spec`. A closure module changed after `activate()` is refused at load. The pinned files' imports stay inside the closure (AST). `vendor` writes nothing into a synthetic clone reached through a link (tree snapshot, empty directories included), refuses unmerged and dangling commits, and never changes a clone file's mode. A path linked through the firmlink or `/.vol` into a clone behind a directory with no search permission, or into a clone that is a link loop, is refused by `roots.lies_in` and by the guard's partial clone check (26fb4c4), and so is a path through a directory with no search permission that holds a link into the clone (4ddf966). Planted deps-tree modules (`extra_mod`, `scripts.backup_metadata`, `nt`, `_winapi`, `_wmi`, `org`) are not found after `rx`'s import and `seal()`, and the deps directory is not on `sys.path`; the closure's AST check flags every name outside the standard library (3f86e34). An empty `sys.path` entry with the cwd in the clone refuses, and so does a clone or an entry that cannot be judged (c00461c). `tools/vendor_research.py` run directly refuses with `launcher_required`, marker or not, and leaves the HOME as it was (9e6dfce). |
| I-14 | Right interpreter | The launcher's absolute path; the version check | Only 3.13 and 3.11 are accepted; 3.12, 3.14 and 3.15 are refused. |
| I-15 | Paper fidelity | Exact mode, the yield tracker, position-based re-seeding | The parity contract (section 7.4), the yield-tracker oracle test, the no-look-ahead re-seed test, the full-cancel test, and `journal.verify()` for every session. |
| I-16 | Agents are not handed Yu's token or real rows by the code. This is a code-path property: the code never prints them, but a same-uid agent that disobeys rule 6 is out of reach. | Single-use codes printed only by `open` (to `/usr/bin/open`), `ssh-session` and `--print-url`; token in memory and registered with `secret`; aggregate-only diagnostics; error mapping; headless commands read real roots only from reviewed code (section 8.6) | Test runs capture stdout and stderr and assert no token or code pattern. Tests plant leaks (`os.write(1, ...)`, a child process, an id-shaped integer): a headless command carrying one, from a dirty checkout or from a commit that is not on the first-parent line of `refs/remotes/origin/main` after the operator's fetch (ancestry and first-parent membership both), is refused before any real root is read (the reviewed-code gate, section 8.6). A `selfcheck` run over fixtures does not print the fixture's synthetic names or prices. A synthetic member with a bad hash or a truncated line produces no market-id or event-id pattern on stdout, stderr, `logs/` or HTTP. |
| I-17 | No engine during Nuance's runs | The run marker, checked before anything is written under `~/betangel-data` and on every tick. Nuance's wrapper creates it with O_EXCL (Q-N3). `run/realdata.lock`, which every real-data process holds shared, from before `TMPDIR` until it exits, with the marker re-checked under it, and Nuance's wrapper takes exclusive (section 6.8; Nuance's PR #2 review, item 6; 596d052, 18de53e, fbbc0c3). The marker is a stop request: running commands drain, and the wrapper's locks, not the polling, keep the upstream run apart. Nuance's wrapper waits at least 60 s for each lock, `engine.lock` and `realdata.lock`, then refuses its own run (fails closed) if it is still held. | A marker present at start refuses the engine, real-data commands, `vendor` and `bin/suite test` on both interpreters; only `stop` skips the check. An unreadable marker refuses them too. A marker appearing during a test run stops it before its next test. A headless command running when the marker appears stops before its next member, and the wrapper's `LOCK_EX` waits for it. Stand-ins for `catalogue` and `selfcheck` show that a real-data command takes `LOCK_SH` before it creates `TMPDIR` and re-checks the marker under the lock; the test for each real-data command is owed with its handler (section 6.8, "Owed"). `stop` runs while the marker exists and the wrapper holds `LOCK_EX`, taking nothing and making no `TMPDIR`. A stand-in wrapper's `LOCK_EX` waits for a holder and fails closed at its deadline. A headless holder stops at its next member. The guard refuses removing or replacing `realdata.lock`, and moving or replacing `run/` (`run_lock_protected`), and any suite write in `lab-runs/`; `arm()` refuses a `run/` or lock that is a link (`run_lock_invalid`), and a root in, around or onto `lab-runs/` (`root_overlaps_lab_runs`; c3b0c61). A marker appearing mid-session freezes the engine with no writes (tree diff), and it exits within the grace period, releasing `engine.lock` within about 35 s. |
| I-18 | Yu's real-data viewing, and real-data output to agents, run reviewed code | Release copies with `RELEASE.json`; a working checkout runs synthetic mode only; headless commands read real roots only from a release copy or a clean checkout of a commit on the first-parent line of `refs/remotes/origin/main` (ancestry and first-parent membership both), after the operator's fetch (section 8.6). It stops accidents, not same-uid rewrites. | `serve`, `open` and `ssh-session` from a working checkout refuse a non-synthetic data root. `selfcheck`, `catalogue`, `diagnose` and `ledger-summary` from a dirty checkout, from a commit that `refs/remotes/origin/main` does not contain (a local merge, or a tag named `main`), or from a commit inside a branch merged into it (off its first-parent line), refuse one too. A modified file in a release copy is refused. `bin/suite release` refuses a commit that `refs/remotes/origin/main` does not contain, and one off its first-parent line. |
| I-19 | Pause unless watched | Stream-drop, visibility, heartbeat and stdin-EOF detection; grace and takeover | Dropping the stream cleanly, hiding the page, or closing stdin pauses the clock within 2 s. A silent disconnect is bounded only by about 3 min today. Owed before Phase 1b: no request from the playing controller for about 5 s pauses with `not_watched`, tested with a peer that reads and never closes (section 8.6). A takeover within the grace period keeps the session. Expiry marks it `abandoned`. |

**The guard's scope** (Astra's PR #1 review, item 3). I-2 to I-6 hold for the calls the audit hook sees and the calls `arm()` wraps, in a process that has armed the guard. They are defence in depth, not a sandbox. Deliberate code in the same process can reach a child, a socket or a write by routes the hook does not see, and `guard.py` lists the known ones (for example `subprocess`'s own reference to the original `fork_exec`, a fresh instance of the built-in `posix` module, and an extension loaded before `arm()` and then taken out of `sys.modules`). So the rules stay rules: the engine never starts a worker process, and nothing turns the guard off (sections 3.2 and 3.9). What each mode allows differs (`guard.py`, "Subprocesses by mode"):

- **engine:** before `seal()`, the one argv shape of I-5, `/usr/bin/open` with the bootstrap URL (the git probe is refused since round 6); after it, no child. Its write roots are the state root and, once agreed, the suite root. It is the only mode that may read in `~/betangel-data`, where Phase 1a reads the data roots.
- **vendor:** before `seal()`, exactly the five git argvs of `tools/vendor_research.py`, each with an exact environment; after it, no child. Its write roots are the state root, the share directory `~/.local/share/betangel-suite/` (narrowed to its deps directory on phase0/viewing) and the checkout's `pin/`. It runs only as `bin/suite vendor` (9e6dfce).
- **uisnap and stop:** no child, in either phase. They are modes of their own only so that neither is given the suite root: their only write root is the state root (lab-Claude's decision, on Nuance's answer to lab-Claude's question 2 of 2026-10-17, conditions 2 and 3, and Astra's re-review of PR #2; 8102f99). `cli.OWN_MODE_COMMANDS` maps `test`, `vendor`, `uisnap` and `stop` to their own modes and every other command to engine mode.
- **test:** the runner never seals. It may start the pinned interpreters with `-I -S -B`, `bin/suite` through `/bin/sh`, and `git` under its `TMPDIR`. Its only write root is the state root, never the suite root; tests use temporary HOMEs.
  - Every interpreter child, whatever follows `-I -S -B`, and every `bin/suite` child needs an explicit environment whose HOME, the roots under it and `TMPDIR` keep out of the runner's data home, by realpath and identity at spawn (`subprocess_refused`; Nuance's PR #2 re-review, F2; 96f8a90 for launcher children, and 8e751d6 for every interpreter child, after lab-Claude's round-5 review found `-c` code that arms the guard itself unchecked). Since cb40c7e the environment is judged item by item, as `subprocess` hands it to the child: an environment that is not exactly a `dict`, a key that is not exactly a `str`, two keys equal once encoded with `os.fsencode`, or a value that is not exactly a `str` or `bytes` is refused (`subprocess_refused`; lab-Claude's recheck of round 5, low item 1), and the git children of the runner and of `vendor` are judged the same way. A child is guarded only if it arms the guard itself; what it does with its environment after it starts is conduct.
  - Its git gets an exact environment allowlist, as vendor's does (`runner_git_ok`; Nuance's PR #2 re-review, F6; Astra's re-review of PR #2: "adopt an exact key/value allowlist, as vendor does"; dd95582). Required: `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1` and the network switch. Allowed: `PATH=/usr/bin:/bin`, `GIT_TERMINAL_PROMPT=0`, HOME and `TMPDIR` (each a directory under the runner's `TMPDIR`, by text and realpath), `LANG` and the synthetic identity keys. Anything else is refused, `DEVELOPER_DIR` and `SDKROOT` included: with `DEVELOPER_DIR` set, `/usr/bin/git` ran another `xcrun` (Nuance's probe).

In every mode the hook refuses `os.system`, `os.exec*`, `os.spawn*` and `os.fork`, a direct `_posixsubprocess.fork_exec` and a fresh load of it, importing `multiprocessing`, `ctypes` or a subinterpreter module, and every network connect and lookup but I-3's one exception. In every mode but engine it also refuses reads in `~/betangel-data` (I-6; 0a3ed65).

Review of `guard.py`, `rx.py`, `errors.py`, `release.py`, `runmarker.py`, `api/`, the launcher, the boundary tests, the hygiene scanner and pin bumps is routed to Astra; `engine.py` and `roots.py` go to Astra and Nuance jointly (section 3.9). `ui/`'s order-sending paths and `tests/test_ui_assets.py` go to Astra too (and the paper keys to Nuance as well), and a test file goes to the reviewers of the modules it imports (Yu's answers of 2026-10-17). Lab-Claude also proposes Astra for `cli.py`, uisnap and the staged scripts; that is open (Q-N12).

---

## 11. Testing strategy and tooling

- **Python.** stdlib `unittest`, run by `bin/suite test`, which is equivalent to:
  `cd ~/betangel-suite && env -i ... BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.13 -I -S -B -m unittest discover -s tests -t .`
  `tests/__init__.py` activates the deps clone through `betangel_suite.pin`: the closure finder, with the deps directory never on `sys.path` (3f86e34). It runs on python3.13, and the full tier runs again on python3.11.
- **Two tiers.**
  - **Fast** (under 60 s): run on every change, as its own step. The pre-commit hook runs only the hygiene scan (`tools/pre-commit`), not the tests (Astra's PR #1 review, item 7).
  - **Heavy** (opt-in): parity seeds, the 200 random seek points and performance.
  - **python3.11 is not opt-in.** The fast tier runs again on python3.11 (`bin/suite test --py311`), and a PR's tests pass on 3.13 and 3.11 at its accepted head SHA (sections 2.2.1 and 12). An earlier version of this list put python3.11 in the heavy tier (Nuance's PR #1 re-review, finding 15).
  - Neither tier starts while a Nuance run is announced. `bin/suite test` refuses both tiers, on both interpreters, while the run marker exists (section 6.8; Nuance's answer to Q-N14). A run already going stops before its next test once the marker appears; the test then running finishes first.
  - Each run records its runtime.
  - Oracle fixtures are capped at about 2,000 messages and 6 runners, because the oracles are slow: `run_paper_replay` takes 141 s and 1.98 GB on a 60k-message market.
- **JavaScript.** `~/.local/bin/node --test ui/tests` (built-in `node:test`, no npm). It covers:
  - the tick map against a JSON export of `LADDER_CLASSIC`;
  - ladder window geometry, frame application and idempotency;
  - the key map (no conflicts, every key mapped to a command);
  - no automation, owed before 1b (section 8.3): a repeated key (`repeat: true`) sends nothing, and with fake timers no timer path reaches an order command;
  - formatters that take integer pence and hundredths only;
  - stream reconnect with backoff.
- **uisnap (Phase 0).** `tools/uisnap` is one `swiftc` file built with the Command Line Tools: no Xcode, no install and no Screen Recording permission. It snapshots its own view only.
  - **How it works.** It starts a **synthetic-only** engine on an ephemeral port; that engine refuses every configured data root. An offscreen WKWebView loads the page and drives keys and clicks through `evaluateJavaScript`, then writes PNGs that lab-Claude reads.
  - **What it is for:**
    - in-browser tests that `node:test` cannot run (canvas, DOM, stream handling);
    - layout checks at the Air's Safari viewport (about 1470×830 pt);
    - the seed of the L1 shell.
  - *Measured:* it built in 15 s, rendered a canvas ladder to PNG, and received chunked NDJSON at 100 ms pacing, with no permission prompt.
  - It runs in the lab's logged-in GUI session.
- **CI-free.** No hosted CI. Tests run on the lab, and Nuance can run them on the Air.
- **Fixtures.** `tests/fixtures/gen.py` writes synthetic PRO-shaped streams (reserved ids) with suspensions, images, removals, version changes, 503 windows, in-play and CLOSED. It also writes trd dips for the conservative-parity property, rising trd after a re-seed point, non-finite SP sizes and prices, and markets with no parseable marketTime. A definition with no `priceLadderDefinition` is required (Nuance's BASIC and PRO counts found the key in no market) and is built on phase0/http (the `no_ladder_definition` option, f23ba3f; section 7.1). Also:
  - a synthetic TAR in the documented member layout (month 2015-05), run through the vendored `ingest_archive` and `index_archive` into a temp root, so the catalogue and reader are tested against real research code;
  - a 2026-dated variant that must be refused.
  
  Real markets are larger than random walks (5-44 runners, 721-6,166 book entries), so the generator also takes size parameters from the section 6.7 aggregates.
- **Test groups:**
  1. **Boundaries:** AST, import closure, audit hook, launcher (including the SSH checks before `env -i`) and environment refusals, route table, OperatorClick and `TestOrder`, release copy, run marker (I-1..I-8, I-17, I-18).
  2. **Data:** catalogue fields, the outcome leak test, research months not written, head and manifest checks, integrity and `decompressed_bytes` refusal, the truncated member, reader parity with `market_index._messages` (including a `not_json` line straight after a multi-message pt batch), month gate, `month_unknown`, roles from the pinned contract, error mapping (no ids in any output).
  3. **Replay:** yield-tracker parity with `snapshots_from_recording`; seek determinism (snapshot `canonical_sha256` after `seek(t)` equals a linear replay to t); checkpoint restore, including the high-water tracker; atomic pt batches; SP tap timing; SP non-finite invalidation shown.
  4. **Paper:**
     - the parity contract, including pending orders at CLOSED and at the end of the member;
     - the conservative property and the no-look-ahead re-seed;
     - the full-cancel test (EXECUTION_COMPLETE, never UNKNOWN);
     - a click followed within 500 ms by STOP, Esc, Z, X, Shift+Esc or a click on the order, split by mode (Q-N5; section 7.6). In live-parity mode the order activates at its A, with any immediate fill, and its unmatched rest is cancelled, never UNKNOWN; after STOP this happens with the display frozen. In exploration mode it ends REFUSED with the withdrawal reason and never activates. Void within 500 ms withdraws it in both modes, with void's own reason. While the run marker freezes the engine, nothing activates;
     - the end statuses and the next-start sweep (section 7.10): one test per reason, from its trigger, SIGHUP and the run marker included; the sweep over SUBMITTING, EXECUTABLE and CANCEL_PENDING orders, with `journal.verify()` first and no clock regression;
     - if the system-stop proposal is agreed (section 7.1): `bin/suite stop`, expiry, failure and recovery each reduce through `PaperDesk.stop_all(SystemStop)` with no click, and the AST test finds `SystemStop(` only at its mint sites;
     - the practice stop (section 7.2): the UTC day, a session over midnight, voided and interrupted sessions, an unreadable session (refused), and the check before the click;
     - incremental folder equals `fold()`; `journal.verify()`; the session journal's clock is the `SimClock`;
     - deterministic re-run from `commands.jsonl` (synthetic mode only);
     - V-rule refusals journal nothing (V0, V5, V6, V9 codes included); live-parity refusals; STOP; forward-only and void;
     - writes of `session.json`, `report.json` and a note through the upstream writers.
  5. **Arithmetic** (randomised, integer pence):
     - What-If equals the sum of `order_pnl_pence`;
     - outcomes after greening are equal within 1p, or the green-up is correctly refused;
     - commission is charged only on positive totals;
     - the indicative Rule-4 figure equals `market_realized` where both apply, and two removals at different pts give the latest first-removal cut-off (section 7.9);
     - the exposure oracle agrees on both bases.
  6. **HTTP security:**
     - section 9.2 items 1-9 and the headers, against a real server on an ephemeral loopback port;
     - bootstrap single use and expiry; takeover invalidating the old token;
     - error responses before routing; HTTP/1.1 chunking and keep-alive.
  7. **UI (uisnap):** synthetic screens, keys and stream handling, at the Air viewport.
  8. **Performance** (heavy tier; generous thresholds): synthetic markets sized like the real p50, p99 and max meet the section 6.7 budgets, and RSS stays at 600 MB or less with 2 cached markets.
  9. **Upstream** (heavy tier, on pin bumps only): the upstream offline suite at the pin (section 3.5), plus the contract test.
- **Real-data smoke** (local only; never in git; never while the run marker exists; only from reviewed code, section 8.6). `bin/suite selfcheck --sample N` opens N random engineering-year members. For each it verifies hashes, replays to CLOSED, and writes a journal containing only notes. It **places no orders**: scripted orders on real data would need a ruling (R-6). It prints **counts and timings only**.
- **Manual acceptance.** After each phase, Yu works through a written checklist in Yu's direct channel (section 3.9): keys, latency, readability on the Air through the tunnel.
- **Review gates.** As routed in section 3.9. Lab-Claude never accepts its own Collab edit tasks.

---

## 12. Phases

**How to read the estimates.** Estimates are *lab work* in weeks; review waits come on top. Each phase has two exits:

- a **lab-done** exit: tests green and a synthetic demo;
- a **review-accepted** exit.

Lab-Claude continues on stacked branches while reviews queue. Lab-Claude also carries other workstreams (agenttool, Kingdom, Cloudflare), so it is not a dedicated developer.

| Phase | Scope | Lab-done exit | Review-accepted exit | Estimate (lab work) |
|---|---|---|---|---|
| **0: Scaffold, governance, pin, guards and viewing** (lab, synthetic only) | **Governance and pin:** the suite's AGENTS.md, README and this document; `pin/betangel-research.json` and `tools/vendor_research.py`.<br>**Engine and guards:** the launcher (SSH checks before `env -i`); `guard.py`; `rx.py` with error mapping; `roots.py`; `release.py`; `runmarker.py`; the hygiene scanner and its git hooks.<br>**Fixtures:** the synthetic generator, including the synthetic TAR through the vendored ingest and index.<br>**HTTP:** the skeleton (bootstrap code, token, Host, Origin, CSP, closed routes, HTTP/1.1 chunked stream) streaming one synthetic market's best prices.<br>**Viewing:** `ssh-session` with pause-unless-watched, heartbeat and takeover; `bin/suite release`; the staged viewer-key and sshd drop-in script; the Air-side self-test; `tools/uisnap`.<br>**Tests:** I-1..I-14 and I-16..I-19, with I-8, I-11, I-12 and I-16..I-19 in part only (synthetic mode, and the commands Phase 0 builds); the rest is in the 1a and 1b exits.<br>**Coordination:** the Phase 0 packet to Yu (R-1..R-7, Q-Y8) and to Nuance (Q-N1..Q-N5, Q-N12), and a Collab coordination task. | Tests green on 3.13 and 3.11. The closure is the 25 allowlisted modules. The hook refuses TEST-NET. A tampered pin is refused. Nothing is written outside the roots. uisnap PNGs of the synthetic ladder. **M1: Yu sees a synthetic ladder** on the lab screen (*target 2026-10-29*); from the Air once R-2 is installed, the Phase 0 stack is merged and Yu has released it (section 8.6). | Nuance agrees the allowlist, pin, state root and **run marker**, recorded at the merge-candidate SHA (Nuance's PR #2 re-review agreed the state root and marker halves as built at 823c194, pending its findings F4 and F5, which are fixed on this branch in ff35218 and c3b0c61; Nuance's review of PR #5 agrees both halves as built at 52a9edc, on conditions, and Nuance confirms the agreement at the merge SHA; Q-N3). Astra has reviewed the guard, boundaries and launcher. Yu has answered every packet ruling Phase 0 needs: R-2, R-4 and Q-Y8 (section 2.2.1). R-7 stays at its stated default until Yu picks, and R-3 has Yu's answer as relayed by Nuance on 2026-10-18 (confirmed by Yu in Yu's own hand on 2026-10-19; section 2.2.1); both gate Phase 1b, not Phase 0. | 1.5-2 weeks |
| **1a: Data layer, catalogue and read-only replay ladder** | **Entry gate:** the four git hooks are live on the lab, as section 5.6 sets out (Nuance's PR #2 re-review, F9).<br>Discovery of indexed roots; head and manifest checks; the spoiler-free catalogue (roles by `market_month`, research months not written); the verified in-memory member reader with the tighter limits; the yield tracker, checkpoints on the new schedule, clock and frames; the SP and definition tap. UI: picker, canvas ladder, one-click grid, countdown, banner, replay controls, chart strip, problem reports. The viewed-markets ledger and `ledger-summary`. Synthetic first. Real-data checks are counts only. | The synthetic UI is complete and accepted through uisnap and Yu's checklist **without PRO**. Real BASIC checks (counts only, from a release copy or a clean checkout of a commit on the first-parent line of `refs/remotes/origin/main`, ancestry and first-parent membership both, after the operator's fetch; section 8.6; and only once the runbook's widened L1 check has landed on the lab, as section 3.7 defines it): the catalogue shows 12,200 engineering-year WIN markets, hides research months and holds no outcome fields; 200 BASIC members pass the reader smoke. Reader and yield-tracker parity pass, as does seek determinism. I-11 and I-12 are tested in full (catalogue, reader and tap). I-16, I-17 and I-18 are tested in full for the headless commands (`selfcheck`, `catalogue`, `diagnose`, `ledger-summary`): planted leaks, one I-17 test per command with the real-data lock, the ledger write freeze, and the reviewed-code gate. The reader refuses while `roots.STATE_ROOT_AGREED` is False (tested; section 5.2), and no data root is read before Nuance's agreement of the suite root is recorded. | Nuance reviews the data path. Yu accepts the synthetic UI. | 2.5-3.5 weeks |
| **M-PRO: first real PRO race** (its own milestone) | Needs Nuance's PRO ingest and index (Q-N4): done on 2026-10-19 (`pro-ingest-01`; section 2.4). Ingest and index are single-threaded and read every line of every member: about 100 GB decompressed and about 380M lines, so *inference* about 1.5-3 h of CPU; Nuance measured 1,230 s for the ingest and 4,499 s for the index. The run marker covered it. | PRO catalogue built (counts only); open budgets met on real members (p99 ≤ 2 s, max ≤ 8 s); the SP non-finite counts recorded (owed: they need Nuance's small reviewed counter, section 6.6); Nuance's `priceLadderDefinition` count on the PRO definitions: recorded, 0 of 12,208, which confirms that the key is absent (section 7.1). Yu watches a real PRO race from T-10 to CLOSED at 1-10x, on the lab screen or through the tunnel, from the release copy. | Yu's acceptance. | Not dated: about 2-3 days of lab work once an engine may run with the real HOME, which waits for the runbook's widened L1 check (section 3.7) |
| **1b: Paper trading** (after R-1, R-6 and R-7; real-data journal writes only once Nuance's agreement of the run marker is recorded; real paper clicks only once U-10, or a V9 ruling by Yu, has landed, section 7.1) | PaperDesk with OperatorClick, and `TestOrder` in synthetic mode only; `validate_place`; exact mode with position-based re-seeding; activation, including at CLOSED and at the end of the member; cancel with the correct split, the pending-order handling Q-N5 sets (section 7.6) and keys; STOP, the end statuses and the next-start sweep (section 7.10); lapse at the off and at close; settle at 2%; positions, exposure on both bases, green-up; the queue tracker; Rule-4 official and indicative figures; journals, `commands.jsonl`, sessions, attempts and void; the live v1 shadow badge, its R10 line included; cap profiles and the practice stop; the debrief. With R-7 = ladder trading: exploration mode (replace, drag, size reduction). | The parity contract and conservative property hold; `journal.verify` passes for every session; deterministic synthetic re-run; the arithmetic and exposure property tests pass; the pending-order tests, split by mode as Q-N5 sets (section 7.6), and the full-cancel test pass; the end statuses and the next-start sweep are tested (section 7.10), and so is the practice stop (section 7.2); the 5 s `not_watched` pause test passes (section 8.6), which completes I-19; I-17's mid-session freeze is tested with journal writes; I-8 is tested in full (`PaperDesk` and `OperatorClick`, and `SystemStop` if the proposal in section 7.1 is agreed); the re-seed test of Q-N7 passes. Real paper clicks pass V9's ladder check: U-10, and any V9 ruling by Yu under D-5, has landed (Nuance's BASIC and PRO counts found the key in no market; section 7.1). | Nuance and Astra review the paper path. Yu completes 10 practice races with no confusing refusal or mismatch and confirms the keymap. | 3-4 weeks |
| **1c: Practice log, polish and MVP sign-off** | Practice log and CSV export; sounds; keymap overlay and settings; market overview; exploration mode if not already in 1b; docs (data-handling, keymap, threat model). | No data-hygiene findings in the scanner. MVP tagged. | A week of short sessions by Yu and a written feedback round. Release copy installed. | 1-1.5 weeks |
| **Total to MVP** | | | | **about 8-11 weeks of lab work, plus review waits** |
| **Later L1: native macOS shell** (before any live click) | A SwiftPM executable (AppKit, WKWebView with `WKWebsiteDataStore.nonPersistent()`, `WKURLSchemeHandler` `suite://`), grown from uisnap.<br>**It runs on the Air**, and reaches the lab engine with no forwarding: the forced command `suite ssh-session --stdio` bridges the SSH channel's stdin and stdout to the engine's Unix socket. The viewer key then becomes plain `restrict`, with no port-forwarding.<br>The browser TCP tunnel stays only for the browser MVP.<br>It is built on the Air from the reviewed merge SHA: the Air has the Command Line Tools 26.4 and Swift 6.3.0 (Nuance, Q-N13). There is no lab-build fallback. It is ad-hoc signed for arm64 (M2). There is no Xcode, Apple ID or distribution.<br>Menu-bar STOP. Global hotkeys need Accessibility or Input Monitoring, which only Yu can grant. | Every MVP feature works with no TCP port open on either machine (`lsof`). A peer from another uid is refused. A tested deny-all content rule keeps the page from reaching any Air loopback port (section 8.6). | Astra's security review; Nuance agrees the Air-side install. | 2.5-4 weeks, including the Air-side install, which depends on Nuance and Q-N13 |
| **Later L2: delayed stream on the Air** (Nuance-owned) | An Air-side package, in a separate repo never cloned on the lab, reuses the suite UI against a delayed-stream view or Air recordings, for integration only. DELAYED banner; 3 levels, 180 s conflation (constants.py:164-167), so practice value is low; recorder ceiling 180 markets (constants.py:216). DELAYED is the only paper source on the Air. Recordings never come to the lab. | An Air session with 0 orders and the DELAYED banner. The lab stays credential-free. | Nuance and Astra. | 1-2 weeks (Nuance) |
| **Later L3: live stage-and-type within D1-D5** (Air, after the £499 key and gate G1) | The suite shows the exact `cli.py place` command and the `presence.order_echo_line` text. Yu types it in Yu's own Terminal at `/dev/tty`. The gateway fetches its own live book and runs every check. The suite never types keystrokes or automates Terminal. A live-journal display would need P-12. Live-key market data is shown only in sessions that place real bets, never for paper (section 2.3).<br>**G1:** buy the key (Yu has committed to it); before buying, ask Betfair Developer Support whether low-volume betting from a mostly-viewing ladder risks read-only deactivation; set a website loss limit and confirm it covers Exchange losses; Nuance runs the outstanding live T-tests. | The first live orders are journaled and reconciled within the default caps, and Yu has reviewed them. | Yu. | 1-2 weeks of suite work, plus Nuance's testing |
| **Later L4: policy-gated live one-click** | Only after P-2..P-6 are approved. Native shell only, never a browser tab. Orders still go through `gateway.py` with an `operator_gui` source. | Each amendment has Nuance and Astra review and Yu's written approval. Upstream boundary tests updated by Nuance. | Staged rollout at minimum caps. | 4-8+ weeks, mostly upstream |
| **Later L5: automation research** | Offsets, timed fill-or-kill, stops, trailing stops and auto-green as simulated intents on historical replay. They need P-1, or they live inside `betfair/backtest` (Nuance). The rule engine has no order sink other than paper. | P-1 approved, or a backtest-side design. | — | Not estimated |

---

## 13. Bet Angel feature map

The table is from the research shortlist, corrected:

- SP display needs no repo change (a suite-side, display-only parser; R-5), but SP non-finites already affect book validity;
- automated orders are not allowed outside backtest;
- live is a typed slip today;
- the delayed key has low practice value;
- the recorder ceiling is 180 markets.

| Feature | Bet Angel equivalent | Priority | Suite plan and notes |
|---|---|---|---|
| Market browser | Market selection tree, quick picks | **Must** | MVP: a spoiler-free catalogue of the PRO replay year (1a). Live "today's racing" quick picks come later on the Air (L2/L3). |
| Price ladder: full depth, traded per price, LTP, centre, 350 ticks | Ladder | **Must** | 1a, from PRO replay. The delayed key would show only 3 levels. |
| One-click grid: best 3, WOM, book %, matched | One-Click screen | **Must** | 1a for display, 1b for paper clicks. The WOM convention is documented (Bet Angel uses the lay side). |
| Freshness banner | Responsiveness indicator | **Must** | 1a: REPLAY, last change age, effective speed, pause reason. DELAYED and LIVE come later. |
| Replay player (seek, speed, pause) | None (Bet Angel has no replay) | **Must** | 1a. This is the suite's main advantage over Bet Angel. |
| Paper LIMIT/LAPSE by click, whole-bet cancel, PAPER tint | Practice mode | **Must** | 1b, paper-v1, operator clicks only. |
| Per-runner position, What-If, P&L | What-If, local P&L | **Must** | 1b, suite code checked against pnl, with exposure on both bases. |
| Green-up / close trade | Trade profit calculator, Close Trade | **Must** | 1b: preview, then confirm. Paper only. Live is blocked by worst-case accounting (P-5, P-6). |
| Countdown and market status | Countdown, alerts | **Must** | 1a. Races can start early: in-play flip versus scheduled off. |
| Kill / stop | Cancel all | **Must** | MVP: paper STOP (UI, key, CLI). In live-parity mode it activates each pending order at its own A, then cancels the unmatched rest, as live cannot recall an order in flight; in exploration mode it withdraws pending orders (section 7.6). The real kill switch (`killswitch.engage`) comes later on the Air. |
| Journal, activity log, caps panel | Activity log, transaction counter | **Must** | 1b: journal `verify()` status; live v1 shadow caps. |
| Keyboard shortcuts | Shortcuts editor | **Must** (paper) | 1b. No auto-keypress, which would be automation. |
| Charts (LTP, price-volume) | Advanced charts, matchstick | Should | 1a strip, 1c fuller. Built from the stream, not REST. |
| Market overview with projected SP | Market overview | Should | 1c, from the suite's display-only SP parser. U-2 would move SP upstream. |
| Queue-position estimate | EPIQ | Should, planned in 1b | `queue_state()` plus the display-only queue tracker (section 7.11), labelled as an estimate and "not a fill". |
| Drag-to-move, replace, size reduction (paper) | Ladder drag | 1b if R-7 = ladder trading, else 1c | Exploration mode only, amber; live stays P-7/P-8. |
| Sounds and notifications | Alerts | Should | 1c WebAudio. Native notifications come with the shell (L1). |
| Settings, stake presets | Profiles | Should | 1c, within the cap profile. |
| CSV export | P&L reports | Should | 1c, under the suite root's `exports/` only. |
| Watch list across many markets | Watch lists | Later | Multi-market replay. Live on the Air within 180 markets. |
| Live stage-and-type within D1-D5 | Manual bet screen | Later (L3) | Air, after the £499 key and G1. No repo change. |
| True live one-click | Ladder click (live) | Later (L4) | P-2..P-6 and the native shell. |
| Offset, timed fill-or-kill | Global settings: offset, FOK | Later (L5) | Automation: P-1 or backtest. |
| Stop loss, trailing stop | Ladder stop loss | Later (L5) | Client-side only, so it fails if the Mac sleeps. P-1 first. |
| Dutching, bookmaking | Dutching, Margin Maker | Later | Multi-instruction; needs removals and reduction factors. |
| Guardian-lite rules | Guardian, automation | Later (L5) | Research inside `betfair/backtest` is allowed now (AGENTS.md:9). |
| CSV model outputs driving displays | Stored values from CSV | Later | A bridge to the H02/E03 calibration track. |
| Make Market | Make Market | Later | H03 scalping is deferred until queue, fill and delay models exist. |
| Local scripting API | Bet Angel API | Later | Unix socket only, authenticated; orders only through the gateway path. |
| Selection correlation | Correlation tool | Later | Offline statistics. |
| In-play trading, Keep/PERSIST | In-play trader | Skip (P-9 if reopened) | Outside D1-D5; refused by V9 and V6 in both modes. |
| Live drag-to-move, nudging, partial reduction | Ladder drag | Skip live (P-7, P-8) | Paper-only in exploration mode. |
| Live BSP bets | Take SP | Skip (P-10) | MOC/LOC are outside v1 (V0 refuses other instruction shapes). |
| TPD, Tennis Trader, Soccer Mystic, Risk Meter | Third-party feeds and models | Skip | Licensed feeds; mostly in-play. |
| Excel live sheets | Excel integration | Skip | Windows COM. Use CSV plus Python instead. |
| VPS 24/7 hosting | Bet Angel VPS | Skip | The repo's A4/A10 rules exclude it. Never mask location. |
| Stakes under £1 | Sub-minimum process | Skip | Refused by V5 in both modes. |

---

## 14. Policy proposals for later (proposals, not decisions)

**Process for every item.**

1. Lab-Claude writes `docs/proposals/NNN-<slug>.md` in the suite repo, stating the problem, the exact text or code diff, the safeguards kept, the evidence required, the tests that change, and a rollback.
2. Lab-Claude opens a Collab coordination task for Nuance.
3. Nuance drafts the upstream change (AGENTS.md, docs/betfair-order-path.md, or code) on the Air.
4. Astra reviews.
5. Yu approves in writing.
6. Nuance implements upstream and updates `tests/test_betfair_boundaries.py`.
7. The suite bumps its pin.

Nothing becomes more permissive by configuration alone. **The MVP needs none of these**, unless Yu rules on a V9 change under D-5 for the ladder type; the ladder type, absent from the BASIC and the PRO definitions, needs the upstream change U-10 (below; section 7.1). R-1..R-7 (section 2.2) are rulings on this repo's design, not rule changes.

**A standing constraint for every later phase.** Paper or practice never runs on live-key data, and live-key market data is shown only in sessions that place real bets (section 2.3).

| ID | Proposal | Today | Safeguards to keep |
|---|---|---|---|
| P-1 | Suite-simulated automation: auto-green at the off, stop, trailing stop, offset, timed fill-or-kill and dutching, as simulated intents on historical replay, consumed only by `PaperExchange` | AGENTS.md:9 allows simulated intents only inside `betfair/backtest` | No order sink but paper (boundary test). Labelled "not execution evidence". A separate strategy ref. |
| P-2 | A new intent source `operator_gui`, distinct from `api` | INTENT_SOURCES (journal.py:97); gateway SOURCES (gateway.py:93); `_check_source` (gateway.py:859-863); AGENTS.md:10 says "types at a terminal" | Live only from the native shell, never from a browser tab. `gateway.py` stays the single choke point. |
| P-3 | Replace the `/dev/tty` retyped line for GUI live orders: a native (non-WebView) modal echoing the exact order, a daily typed arming token, Touch ID (LocalAuthentication), and a per-session order budget | `TtyConfirmer` (presence.py:80). Its docstring calls the line friction, not proof (presence.py:1-11). | `/dev/tty` stays as the fallback. Judged on friction and accident prevention. |
| P-4 | A long-lived operator-session gateway on the Air, instead of one login per CLI command | Login cap 30 per 10 min (config.py:41) | Journal-before-send, the first-byte KILL check, never-resend, a gateway-self-fetched book no older than `max_book_age_s`, session expiry and idle lock. |
| P-5 | An order-stream position cache (`esa.subscribe_orders`, esa.py:211) plus a decision on live hedge credit | Live R8-R10 give no hedge credit (risk.py:236; Astra C1: Rule 4 can lower matched prices) | Credit only for positions the order stream confirms, falling back to no credit on any gap. |
| P-6 | Caps for trading-style use: stake, liability, exposure, orders per minute, and `max_instructions_per_request` 1→2 for two-leg greening | DEFAULTS caps (config.py:58-62); ceilings (constants.py:197-217) | Evidence first, from the suite's live v1 shadow statistics. The website loss-limit backstop confirmed. |
| P-7 | D2: reopen live replace (drag, nudge) | `live_replace_removed_v1` (gateway.py:677, :1495) | Replace reconciliation rules; Astra re-review of provisional-child exposure. |
| P-8 | D1: live partial cancel | `live_partial_cancel_removed_v1` (gateway.py:1377) | Low priority. A whole cancel plus a new place covers it, at the cost of queue position. |
| P-9 | In-play scope | V9 `market_inplay` in both modes (validate.py:104-105) | betDelay and delay modelling, PERSIST semantics, and paper-model extensions first. |
| P-10 | BSP orders (MOC/LOC), "At in-play: Take SP" | Outside v1 (V0) | The minimum BSP back stake clarified. SP in the snapshot schema (U-2). |
| P-11 | D3: automatic live settlement from exchange-reported P&L | The hand-typed worst-case `settle-market` (journal.py docstring; SETTLE_BASES :84) | Interacts with P-5. Needs a fresh decision from Yu. |
| P-12 | Read-only suite access to the live journal on the Air, for display | AGENTS.md is silent on consumers other than the backtester | Open `journal-live.sqlite` read-only. Never write it or take `.gateway.lock`. |

**Upstream code changes** (not policy; owned by Nuance):

| ID | Change |
|---|---|
| U-1 | Rule-4-aware `pnl.market_realized`: exclude only when a matched bet precedes a removal (pnl.py:53-54). It would remove most of the 49.5% exclusions. |
| U-2 | SP fields (spn, spf, spb, spl, final bsp) in a book snapshot schema v2 (schemas.py:23; book.py:56, :266-294, :476-492). It would also decide whether non-finite SP values should invalidate the whole book (book.py:486-489, :312-317), informed by the first-PRO counts. The suite's tap is then retired. |
| U-3 | Cancels, and optionally replaces, in `run_paper_replay`'s orders file (paper.py:61), so sessions with cancels can be parity-checked. |
| U-4 | A public close/lapse helper on `PaperExchange`, replacing the private `_lapse` (paper.py:585). |
| U-5 | A public strict member iterator in market_index, the semantics of `_messages` (market_index.py:268), plus a public "open member with hash check" helper. |
| U-6 | A public traded high-water seed, or a stepping reader that snapshots at chosen pts, for P1 throughput and suites. Any coarse-cadence advance needs a proof that it is never less conservative (section 6.3). |
| U-7 | A paper-v2 queue model that credits cancellations ahead, calibrated on PRO data and reviewed by Astra. paper-v1 ignores them by design (paper.py:42-46; the sentence is at :45). |
| U-8 | Deferred: a decision on the quiet-market staleness artefact for historical files (section 7.5). It also affects P1. Revisit only if the debrief counts show it matters. |
| U-9 | A distinct paper intent source (for example `operator_paper`) in `INTENT_SOURCES` (journal.py:97), proposed alongside P-2, so journals separate human paper clicks from orders-file replays without relying on `customer_strategy_ref`. |
| U-10 | Needed (section 7.1): Nuance's counts found `priceLadderDefinition` in 0 of the 12,208 BASIC and 0 of the 12,208 PRO engineering-year markets; the PRO count, M-PRO's, confirms the BASIC one. A fact row, and a CLASSIC default only at the book.py:459 call site, for historical ODDS markets. Nuance's (PR #1 review, item 1); it can start now (lab-Claude's decision, following Nuance's PR #1 re-review, finding 5, which did not wait for M-PRO). Any change to V9 itself goes to Yu under D-5. |

---

## 15. Open questions

### 15.1 For Yu

**Phase 0 packet (one page):** R-1..R-7 (section 2.2) and Q-Y8. The other questions are deferred to the phase that needs them.

| ID | Question | Needed in |
|---|---|---|
| Q-Y1 | **R-1.** May the suite drive `PaperExchange` directly, outside the gateway, for paper orders you click on historical replay? Nuance asked for your ruling. betangel-research's own batch replay already does this. The alternative imports the credential-bearing gateway. <br>**Answered by Yu on 2026-10-15 (R-1, section 2.2.1): yes.** | Answered |
| Q-Y2 | **Viewing (R-2).** Recommended: the forced-command tunnel key plus the sshd drop-in, which you install yourself; lab-Claude stages them. In a Safari Private window, replayed prices appear on the Air's screen and in browser memory only. In a normal window, Safari History and iCloud would also sync the URL and title. Is viewing on the Air fine as personal use? <br>**Answered by Yu on 2026-10-15 with R-2 (section 2.2.1): yes.** That the answer also covers the personal-use question is lab-Claude's reading. The browser half is Q-Y11 (answered 2026-10-17). | Answered |
| Q-Y3 | **Commission label (R-3).** You said "Basic 2%". `user_package_verified` on your word, or `user_package_unverified` until you have checked My Account? <br>Asked of Yu in the packet, and not answered there; until then the stated default was `user_package_unverified`. **Answered by Yu on 2026-10-18, as relayed by Nuance: "confirm account is basic 2%", read as `user_package_verified`** (section 2.2.1); confirmed by Yu in Yu's own hand on 2026-10-19. The config default follows through a reviewed change before Phase 1b (section 3.8). | Answered 2026-10-18 (relayed by Nuance); confirmed by Yu 2026-10-19 |
| Q-Y4 | **State root (R-4).** Is `~/betangel-data/suite.noindex` OK for practice journals, the catalogue and exports? <br>**Answered by Yu on 2026-10-15 (R-4, section 2.2.1): agreed.** Nuance's side is Q-N3. | Answered |
| Q-Y5 | **Practice defaults.** Start at T-10 min; 2x until auto-slow at T-3; pause at the off? One-click on by default, or confirm every order at first? | 1b |
| Q-Y6 | **Practice stop** of £20 a day (£200 under the `practice` profile): a paper-only stop, defined in section 7.2 (draft 0.2 called it the practice loss limit). Do you want it at all, and at these amounts? Useful or annoying? | 1b |
| Q-Y7 | **Research-corpus months** (2023-2025): keep them hidden (the default, which protects later research)? Or open them, which needs a ruling id with Nuance and Astra and is logged? | Later |
| Q-Y8 | **Repo workflow.** Lab-Claude pushes branches and opens PRs that Nuance or Astra review (routing in section 3.9). Who merges: you, or lab-Claude after review? May UI-only PRs go on your acceptance alone? <br>**Answered by Yu on 2026-10-16:** "Its all good :) Merge when sensible". Section 2.2.1 records it, with lab-Claude's reading of "sensible", labelled as lab-Claude's. It was not one of the 2026-10-15 answers. An earlier version listed it there, with "Yu can veto or revert any merge"; Nuance found no source for that sentence or for the merge half, and pointed to section 3.9's recommendation as the source of the UI-only half (Nuance's PR #1 review, item 10). **The UI-only half: answered by Yu on 2026-10-17 ("Lets go with what you recommended for all :)"): yes.** UI-only PRs merge on Yu's acceptance alone (section 3.9 defines UI-only). This line had asked it with no recommendation; lab-Claude's message of 2026-10-17 put it again with one. **The governance row: answered by Yu on 2026-10-17 (the same words): adopted, as Nuance recommended** (Nuance's PR #1 review, item 9), with Nuance's PR #2 addition, "changes to AGENTS.md's rules or routing also need Yu" (sections 2.2.1 and 3.9). **Asked of Yu on 2026-10-17, with lab-Claude's recommendation of yes to both, and answered by Yu later that day:** lab-Claude's proposal of a row that sends each test file to the reviewers of the code it tests, so that ordinary test changes do not all go to Yu, in the mechanical form Nuance recommends ("a test → the reviewers of the modules it imports, else Yu"): "yes lets go with what you recommended"; and narrowing UI-only, so that `ui/`'s order-sending paths go to Astra (Nuance's PR #1 re-review, finding 3): "ohh understood. Yes lets go with what you recommended". Both rows are binding (sections 2.2.1 and 3.9). | Answered 2026-10-16 and 2026-10-17 |
| Q-Y9 | **Agents and data.** Confirm that agents never see real rows, the viewed-markets ledger or real-data screenshots. **Caveat:** your OK alone cannot make an exception. A model context counts as an upload. The Betfair Historical Data terms' "No onward distribution" clause prohibits "the use of the Historical Betfair Data by, another organization or individual" unless "a specific agreement in writing with Betfair exists", and Betfair has not ruled on model providers (the clause as quoted in proposal 001, sections 5.1-5.2; proposal 001 is PR #3, not merged; Astra is run by OpenAI). Recommended (Nuance, PR #1 review, item 2): agents never read real values; you describe the shape, or a code-only `diagnose` check runs; real fields only with Betfair's written agreement naming the provider, plus your OK each time, scoped to one problem report and named fields. Until then exceptions are not available (rule 5; section 8.7). **This reworded question: answered by Yu on 2026-10-17 ("Lets go with what you recommended for all :)"): confirmed** (section 2.2.1).<br>**Deny rules: asked of Yu on 2026-10-16, and approved by Yu that day.** Nuance recommended them (PR #1 review, item 3), so that lab-Claude's file tools cannot read, search or list `~/betangel-data` or the install salt. Lab-Claude's Claude Code settings on the lab now deny `Read` and `Edit` of `~/betangel-data`, of everything under it, and of `~/.local/state/betangel-suite/install-salt*` (checked 2026-10-16). Read and Edit are denied; Grep and Glob are unverified; Bash is conduct only (section 9.4: lab-Claude's main session has no Grep or Glob tool, and searches through Bash). Nuance's SSH shell and Astra stay conduct-only. **The optional `~/.ignore`** with `/betangel-data/` (Nuance's suggestion): **answered by Yu on 2026-10-17 (the same words): not added**, as lab-Claude recommended. It would also hide the folder from Yu's own searches, and it would not have helped: it hides a folder only from ripgrep, not from Claude Code's shell `grep` or from `find` (Nuance's PR #2 re-review, F12). | Answered (2026-10-16 and 2026-10-17) |
| Q-Y10 | **Screen Recording: recommended No.** It would be granted to the host terminal (iTerm2) and cover every process under it, and `screencapture` takes the whole display. Any real race on the lab screen would then go into model context, which counts as an upload. `tools/uisnap` gives lab-Claude synthetic screenshots without it. If you still want it, capture would go only through a suite subcommand: that subcommand starts a synthetic-only engine, captures only its own window (`screencapture -l <id>`), and refuses while a real-data engine runs. You would revoke the permission when it is not in use.<br>**The Air too** (Nuance, PR #1 review, item 6). This question also covers the Air, before its first real race. There an agent's shell already passes the screen-capture preflight with no prompt (section 8.6). **A line in the Air's CLAUDE.md** that no agent captures the screen while a suite page or an `ssh lab-suite` window is open (Nuance recommends it): **answered by Yu on 2026-10-17 ("Lets go with what you recommended for all :)"): approved, and in.** Nuance confirmed on 2026-10-17 (08:48Z) that it is in the "Betangel suite" section of the Air's `~/.claude/CLAUDE.md` (Nuance's PR #1 re-review, finding 4). It is a CLAUDE.md rule for Claude Code sessions on the Air; for Astra and other tools it is conduct only. | Lab: not needed. Air: before its first real race (the CLAUDE.md line: approved and in, 2026-10-17) |
| Q-Y11 | **Browser.** A Safari Private window for the suite on both machines (recommended), or a dedicated profile with no Betfair login, no extensions and no iCloud sync? Also, in the lab's Safari: sign out of historicdata.betfair.com, and delete saved betfair.com passwords and betfair.com site data, now rather than after the downloads (mailbox B4 asks for both; Nuance, PR #1 review). <br>**Answered by Yu on 2026-10-17 ("Lets go with what you recommended for all :)"): yes, a Safari Private window on both machines. The clean-up now: agreed by Yu on 2026-10-17, for Yu to do by hand.** **Done:** Yu's words of 2026-10-18, as relayed by Nuance, are "Pw deleted too", which Nuance reads as Yu having done the clean-up on the lab (section 2.2.1; confirmed by Yu in Yu's own hand on 2026-10-19). Agents never touch browser data or passwords (sections 2.2.1 and 8.6). | Answered; the clean-up done (2026-10-18, relayed by Nuance); confirmed by Yu 2026-10-19 |
| Q-Y12 | **Backups.** Is `~/betangel-data` backed up, for example by Time Machine? Journals and exports are licensed derivatives, so where copies go matters. | 1b |
| Q-Y13 | **Ladder.** Higher odds at the top or the bottom? Keep Bet Angel's keys (Z/X, C)? | 1a |
| Q-Y14 | **Analytics.** Mac Analytics auto-submit is on, so a native crash report from python3.13 or Safari could carry data to Apple. Turn sharing off? This is a privacy setting only you can change. | 1a |
| Q-Y15 | **Spotlight.** Add `~/betangel-data` to Spotlight Privacy? The suite root is already `.noindex`, but the data roots and index JSONL are not. | 1a |
| Q-Y16 | **PRO ingest timing.** The PRO year goes to a separate root and leaves P0's BASIC descriptor untouched. May Nuance ingest it before c2b3b3 lands, if Nuance agrees? <br>**Closed as moot** (Nuance asked for this in Nuance's answer to Q-N4): c2b3b3 is merged. The ingest had no date; it was to come after the runbook's section 10.1 released the TAR, under the run marker, with you told. Nuance ran it on 2026-10-19, under the run marker (section 2.4). | Closed |

### 15.2 For Nuance

**Phase 0:** Q-N1..Q-N5 and Q-N12. The others are deferred to the phase that needs them.

Nuance's PR #1 review (2026-10-16) answered Q-N4..Q-N11 and Q-N13. The answers below are Nuance's, and Yu can override them. Nuance's PR #4 review answered Q-N1..Q-N3, and Q-N12 in part; the rows below record those answers, and Q-N3's row also records how Nuance's PR #2 review made it conditional again, and how Nuance's PR #2 re-review agreed it as built. Q-N14 and Q-N15 are asked only on the later branches, and Nuance's answers to them are recorded there; this branch also records Nuance's answers to Q-N14, in section 6.8 and AGENTS.md (Phase 0 status E).

| ID | Question | Needed in |
|---|---|---|
| Q-N1 | Do you accept the engine importing only the 25-module closure in section 4.1, with no risk or capability? Will you treat the contract-tested names (section 4.5) as an interface and flag breaking changes in PR descriptions? Is test-only use of `risk` as an oracle acceptable under INTERNAL_ONLY? <br>**Answered by Nuance** (PR #4 review, 2026-10-16):<br>- Closure: accepted. Exactly 25 modules load (section 4.1). Before Phase 1b, `rx.py` gains wrappers: `StatePaths` with explicit roots, `OrderJournal` with `mode="paper"` and an explicit clock, and `validate_place` forced to paper. `SystemClock` is dropped from the allowlist; no suite code used it.<br>- Contract test: "yes, narrowed". `tests/test_upstream_contract.py` lands on phase0/http; every bump is gated on it, Phase 0's names first (section 4.5).<br>- `risk` as a test oracle: no. It is unpinned; an independent exposure oracle is used instead (section 4.2). | Answered |
| Q-N2 | Is the pin by a network-free local clone (`clone --no-checkout --no-hardlinks` from the lab clone, `checkout --detach`, remote removed, read-only) OK? Or do you prefer `git archive`? Who bumps pins? <br>**Answered by Nuance** (PR #4 review, 2026-10-16): keep 76f71dc, and bump only when a closure module the suite needs, or the month roles, change. "Allowlisted file" means every `PINNED_FILES` entry (section 3.5). The review does not say whether Nuance prefers `git archive` or who bumps pins. <br>**Nuance's PR #2 review answers the rest:** "Keep the network-free clone after 2 and 10" (both fixed: e51b469, 816e832). "Drop 3.5 item 3's git_state reason (11); keep the upstream IN_GIT_CHECKOUT one" (section 3.5). "Lab-Claude bumps in its own PR only to a sha Nuance names on main"; `vendor` now refuses a commit that is not on the research main branch (`commit_not_on_main`; 1d23fdc), because "cat-file -e accepted unmerged and dangling commits". "Nuance reviews every bump; Astra reviews pin and vendor code. Routing is proposed until Yu rules (Q-Y8)." <br>**Nuance's PR #2 re-review checks the ref:** "`refs/heads/main` is right". The lab's `~/bin/betangel-update-test.sh` runs `git fetch -q origin` and then `git merge -q --ff-only origin/main` in `~/betangel-research`, so `refs/heads/main` fast-forwards on every update, and `VENDOR_MAIN_REF` needs no change. | Answered |
| Q-N3 | **State root and the run marker.** Is `~/betangel-data/suite.noindex` acceptable? Following your A5 answer, the suite will not run at all during your runs. Will your run and ingest wrappers write a marker such as `~/.local/state/lab-runs/ACTIVE`, and wait for `~/.local/state/betangel-suite/run/engine.lock` to be free before touching sources or data? <br>**Answered by Nuance: yes to both** (PR #4 review; mailbox, 2026-10-16 13:41Z).<br>- Root: `~/betangel-data/suite.noindex`, on three conditions (section 3.7): (1) Nuance never uses `~/betangel-data` or `suite.noindex` itself as a data or lab-state root; (2) before Phase 1a, the suite refuses a data root that equals, contains or lies inside `suite.noindex`, `lab-state` or `logs`, or lies inside `incoming/`, comparing by file identity (owed before Phase 1a); (3) the marker half is agreed first. `roots.STATE_ROOT_AGREED` was set True after this answer.<br>- Marker: `~/.local/state/lab-runs/ACTIVE`, on Nuance's terms (section 6.8). Nuance's wrapper creates it with O_EXCL: "Wait at least 60 s for engine.lock, and fail closed if it is still held. Treat a missing lock file as free and any other error as busy". Nuance measured the lock free only after 30.23-30.60 s (PR #4 review, item 15); the engine may hold it for about 35 s after the marker appears. <br>**Nuance's PR #1 review (item 5) adds:** the marker covers every upstream step on real roots, by rule; Nuance adds a marker step to each block of the runbook's section 10.1; and `run/realdata.lock`, which real-data processes hold shared and Nuance's wrapper takes exclusive (section 6.8). <br>**Conditional again since Nuance's PR #2 review** (2026-10-16): "agree the root half after 1, the marker half after 6". Nuance's PR #2 finding 1 is about roots that resolve into `~/betangel-data`; Nuance's finding 6 is the marker protocol, which Nuance merges with item 5 above (section 6.8). That review also moves the flock of Nuance's wrapper from `ACTIVE` to a never-unlinked `lab-runs/LOCK`, held for the whole job. <br>**Root half:** Nuance's PR #2 item 1 is fixed on this branch (62c39c6, 851885a; section 3.7, "Placement"). Nuance's PR #2 review adds: "Nuance's wrappers refuse roots in suite.noindex, and duplicate roots, by identity"; the suite's own duplicate check is owed before Phase 1a (section 5.2). <br>**Marker half:** in Nuance's PR #2 item 6 and PR #1 item 5 Nuance asked for a separate lock (that it is never unlinked is lab-Claude's design, section 6.8), `LOCK_SH` with a re-check, checks between members, a renamed catalogue, and a wrapper that waits at least 60 s for `LOCK_EX`, then refuses its own run (fails closed) if the lock is still held. It is built on this branch (596d052, 18de53e, fbbc0c3; section 6.8). Whether `test`, `uisnap` and `vendor` may take no lock was asked of Nuance on 2026-10-17; Nuance agreed that they take none, on four conditions (Nuance's answer to lab-Claude's question 2 of that day; section 6.8). <br>**Nuance's PR #2 re-review** (2026-10-17, answering lab-Claude's questions 3 and 8 of that day): both halves are agreed "as built at 823c194, pending F4/F5", on Nuance's conditions (sections 3.7 and 6.8), and the lock's name is `realdata.lock`. F4 and F5 are fixed on this branch (ff35218, c3b0c61). c3b0c61 changes placement, so by Nuance's conditions the re-check is open again, at the merge-candidate SHA (lab-Claude's reading).<br>**Nuance's review of PR #5 at 52a9edc** (2026-10-19): "Q-N3: I agree both halves, root and marker, as built at 52a9edc", on conditions (a) to (d) (section 3.7). Under (a), a later fix that touches the Q-N3 file set reopens only its own diff; Nuance confirms the agreement at the merge SHA in one line. | Phase 0 (agreed as built at 52a9edc, on conditions; to be confirmed at the merge SHA) |
| Q-N4 | **PRO ingest.** When will you ingest and index it (a date), and what is the final data root (`historic-pro`?)? Is it one archive sha, with index v1 built as for BASIC? A header listing shows 12,208 market files at depth 6, all PRO, including 8 in 2016-May (in no contract split). Is there anything in the index the picker should surface? <br>**Answered by Nuance** (PR #1 review, 2026-10-16):<br>- No date. The ingest comes after the runbook's section 10.1 releases the TAR, under the run marker, and Yu is told.<br>- A separate root, `~/betangel-data/historic-pro`, with one archive sha and the stock index built at code equal to 76f71dc (the BASIC index was built at da44d71).<br>- "12,200 = 12,200" is a match of counts, not of markets (section 2.4).<br>- For the picker: `files[].status` and `complete_before_pt` (section 5.3).<br>- Close Q-Y16 (done).<br>**Done on 2026-10-19:** Nuance's job `pro-ingest-01` ingested and indexed the TAR into `~/betangel-data/historic-pro` under the run marker, with the stock tools at research main 0d32421: 12,208 markets, 12,114 indexed and 94 unreadable (`malformed_runner`), counts only (section 2.4). | Answered; done 2026-10-19 |
| Q-N5 | **Paper semantics.** Is direct `PaperExchange` use with a suite `OrderJournal(path, mode="paper", clock=SimClock)` fine, given Yu's R-1? Intent source `paper_replay` with `customer_strategy_ref` `suite-click` (and `suite-test` in synthetic tests), with click provenance in `note` events, until U-9? Is withdrawing a pending order as SUBMITTING → REFUSED (`operator_withdrawn_before_activation`) acceptable? <br>**Answered by Nuance: yes** (PR #1 review, 2026-10-16), through an `rx.py` wrapper (paper mode, `SimClock`), with `suite-click` refs; journals stay under the suite root. On pending orders, in Nuance's words: "The 500 ms models an order in flight and step shows the activation book, so in live-parity Esc on a pending order activates then cancels; withdrawal only for void and badged exploration; readers use the folded error_code." Section 7.6 records what this changes. <br>**Whether this covers STOP** (lab-Claude's question 5 of 2026-10-17): Nuance answered in the PR #2 re-review, "Yes — STOP is covered", one code path for Esc, Z/X, Shift+Esc, a click on the order and STOP; void's handling is split from STOP's, and void withdraws; "the marker freeze wins". Yu can override it. Round 5 brings sections 6.4, 7.6, 7.10, 8.2, 8.3, 11, 12 and 13 in line (Appendix F). | Answered |
| Q-N6 | **Quiet-market staleness.** Paper V10 and `_activation_refusal` measure age from the market's last change. Real data shows it is rare near the off. Do you want U-8 at all? (Low priority; the relaxation mode is cut.) <br>**Answered by Nuance: not now** (PR #1 review, 2026-10-16). U-8 stays parked. Split stale refusals by time to the off, and revisit if they show in T-10 to the off (from T-30, 13 of 39 markets had gaps over 10 s; section 7.5). | Answered |
| Q-N7 | **High-water seeding.** Is it acceptable to rebuild `PaperExchange` with a suite-built `state` whose `traded_hwm` is raised to the raw running maximum up to the replay time (conservative, no look-ahead)? Or would you rather publish U-6? <br>**Answered by Nuance: accepted** (PR #1 review, 2026-10-16), with a fresh exchange per attempt (Nuance's probe) and finite trd values only; the test is in the 1b exit (section 7.4). | Answered |
| Q-N8 | Is `config.validate_config` under `StatePaths(home=..., root_override=...)` with FORBID_NETWORK (the test-harness override) an acceptable way to validate the suite's paper config? <br>**Answered by Nuance: yes** (PR #1 review, 2026-10-16), if the suite root is agreed and exists first (else `subprocess_refused`), and the object feeds only `validate_config`: its `kill_engaged()` is a false all-clear (section 3.8). | Answered |
| Q-N9 | **SP display (R-5).** Do you confirm a suite-side, display-only parser needs no repo ruling? Do you plan U-2, including whether SP non-finites should invalidate the whole book? <br>**Answered by Nuance: confirmed** on the terms in section 6.6 (Nuance's PR #1 review, item 11: the tap resets at each image; `spb` and `spl` are deltas, cleared while not OPEN; `bsp` only within [1.01, 1000]). U-2 waits for the M-PRO counts. | Answered |
| Q-N10 | **Rule 4.** Will you take U-1? Until then, is the "indicative, exact-case" figure acceptable? <br>**Answered by Nuance:** U-1 not now; it needs a fact row and per-fill pts (PR #1 review, 2026-10-16). Nuance's item 11 sets the indicative figure's cut-off, label and exclusion from totals (section 7.9). | Answered |
| Q-N11 | **Viewed-markets ledger.** Which fields and format do you want, so markets opened in the suite reconcile with your trial ledger? Agents never read the ledger; reconciliation is by code over salted hashes, printing match counts only. Does human practice on the engineering year matter to P0 or P1? <br>**Answered by Nuance** (PR #1 review, 2026-10-16): month level. The fields are a keyed hash, plan, month, role, opened_by, furthest phase, attempts and ruling id. Counts come from `ledger-summary`, with no hash matching: the trial ledger holds no market ids (trial_ledger.py:96). Human practice on the engineering year has no effect on P0 or P1. A research month that is opened becomes inspected (contract.py:39). Sections 5.3 and 5.5 record this. | Answered |
| Q-N12 | **Review routing.** Do you agree the routing in section 3.9 (Astra for guard, rx, errors, release, run marker, api, boundaries, scanner and pins; you for data and paper; Yu alone for UI-only PRs)? Should lab-originated review requests arrive as a lab-journal coordination task plus a mailbox note? <br>**Answered by Nuance: "agree once amended"** (PR #4 review, 2026-10-16). Nuance asked that "every reviewer whose rows the diff touches accepts it at a named head sha", that "engine.py and the roots are reviewed jointly", and that Nuance's row gain `synthetic.py`, `tests/fixtures/`, `tools/export_ticks.py`, `ui/ticks.json` and `replay/`. Section 3.9 and AGENTS.md now say exactly that. <br>**Nuance's PR #1 review (item 9) amends Nuance's view:** a governance row for rule documents (AGENTS.md, this document, `docs/data-handling.md`, `docs/proposals/`, `tools/stage/`) to Nuance and Astra at a named SHA, for Yu to rule on. **Answered by Yu on 2026-10-17 ("Lets go with what you recommended for all :)"): adopted, as Nuance recommended**, with Nuance's PR #2 addition, "changes to AGENTS.md's rules or routing also need Yu" (sections 2.2.1 and 3.9). <br>**Nuance's PR #2 review adds** (Nuance's Q-N12 additions): "config.py, data-handling.md and tests/__init__.py to Astra and Nuance; a fail-closed row for unnamed files; changes to AGENTS.md's rules or routing also need Yu." The first is now a row in section 3.9 and AGENTS.md; it only adds reviewers. The second names no reviewer: section 3.9 and AGENTS.md sent unnamed files to Astra and Nuance jointly, which was lab-Claude's reading. Under the governance row Yu adopted on 2026-10-17, in Nuance's own item 9 text, files that no row names go to Yu, and the fail-closed row now says so; the question put to Nuance on 2026-10-17 about which reviewer it has is moot. Nuance has since withdrawn that row, and recommends lab-Claude's test-file row only in a mechanical form, which is Yu's to decide (Nuance's answer to lab-Claude's question 1 of 2026-10-17, PR #2 re-review). Yu adopted that form on 2026-10-17 (sections 2.2.1 and 3.9). The third was adopted by Yu with the governance row on 2026-10-17, so #2, #4 and #5 each also wait for Yu's approval of their AGENTS.md changes. Nuance also sends "Every touched reviewer accepts the same head SHA" to Yu as a Q-Y8 clarification. <br>**Nuance's PR #1 re-review (finding 3) amends Nuance's own answer here:** UI-only should exclude `ui/`'s order-sending paths, which go to Astra. Asked of Yu on 2026-10-17, and answered by Yu that day: narrowed, as lab-Claude recommended (sections 2.2.1 and 3.9). <br>**Still open.** Adding `cli.py`, uisnap and `tools/stage/` to Astra's row is lab-Claude's proposal, from Phase 0c's review plan, not Nuance's request. It only adds a reviewer; Yu rules on it with you (Q-Y8), and Yu can override it. The review does not answer the second part (how review requests arrive). Nuance asked that Yu be asked to clarify Q-Y8 so that tests must pass on 3.13 and 3.11 at the accepted SHA ("Ask Yu to clarify Q-Y8 so that tests must pass on 3.13 and 3.11 at that sha"). Lab-Claude asked Yu on 2026-10-16, and Yu answered "Its all good :) Merge when sensible" (section 2.2.1). | Answered in part |
| Q-N13 | **The Air later.** Does the Air have the Command Line Tools and Swift? Which Python is there? Will you host the Air-side package (L1/L2) in a separate repo, or in betangel-research, never cloned on the lab? <br>**Answered by Nuance** (PR #1 review, 2026-10-16):<br>- The Air: M2, the Command Line Tools 26.4, Swift 6.3.0, and python3.13 3.13.15 (installed after Nuance's PR #4 review).<br>- The Air-side package goes in a separate repo under Yu's account, never betangel-research, which is cloned on the lab (section 3.1).<br>- L1 is built on the Air from the merge SHA. The lab-build fallback is dropped (section 12). | Answered |

---

## 16. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Review capacity.** Each of Nuance's tasks needs an Astra round (c2b3b3 and c2b3b4, which Nuance was finishing first, are merged). Lab-Claude carries other workstreams. | Elapsed time set by review latency, not coding. | Lab-done and review-accepted exits; stacked branches; one Phase 0 packet; routing proposed up front; UI-only PRs on Yu's acceptance alone (Yu's answer of 2026-10-17; section 3.9). |
| **PRO ingest timing.** It had no date (Q-N4); Nuance ran it on 2026-10-19 (section 2.4). | Real-data milestones slip. | The synthetic UI is accepted without PRO; M-PRO is its own milestone; Q-N4 is answered and done, and Q-Y16 closed. |
| **The runbook's L1 layout check and the suite root (R-4).** Until L1 accepts `suite.noindex/`, the first engine command run with the real HOME, which creates the suite root, would make the lab fail L1. | Nuance's next C0 blocked; real-data milestones slip until the widened check lands. | Nuance chose to widen L1 to accept `suite.noindex/` and `historic-pro/` (an upstream runbook change, authored by Astra and reviewed by Nuance, in the next tooling round). It is on betangel-research's main as 416702f (PR #28) since 2026-10-19. No engine command runs with the real HOME before it lands on the lab (lab-Claude's decision; section 3.7): until the lab's checkout is at a C0 that includes 416702f, with no suite command between that C0's L1 check and the runbook's 5a (Nuance's review of PR #1 at af960fd, F4). |
| paper-v1 is deliberately pessimistic: half of displayed size, no credit for cancellations ahead, unknown queues never fill. Practice may teach that resting orders rarely fill. | Skills and expectations are miscalibrated. | Verbatim assumptions, the queue tracker, fill-quality debrief, the R-7 choice, U-7. |
| About half of races have a non-runner, so there is no official P&L. | Frustration, and pressure for ad hoc fixes. | The indicative figure (section 7.9), the library filter, U-1. |
| 2015-16 liquidity and behaviour may not transfer to 2026. Replaying a race teaches its result. | False confidence. | "Not execution evidence" labels, attempt counter, forward-only sessions, the spoiler-free picker. More recent PRO months cost £230 each and touch research and holdout rules (Nuance and Astra). |
| Exact mode on big fields lags near the off (about 8x at 44 runners; about 3x in the busiest second). | Slower than requested speed. | Labelled effective speed; prefetch never during exact mode; open budgets by percentile. |
| 8 GB memory pressure shared with Nuance's work and two Claude sessions. | Swapping, interference. | 600 MB target, 1 and 1.5 GB caps, an LRU of 2, `run_paper_replay` banned on real data, nice, no engine during runs, heavy tests opt-in. |
| Upstream drift: the repo moves several times a day; private behaviours are mirrored. | Breakage on pin bumps. | Pin with per-file hashes, contract and parity tests, reviewed bumps, U-3..U-6 to retire the mirrors. |
| R-1, R-6 or R-7 is unresolved, or resolved against. | Phase 1b is blocked or reshaped. | Ask in the Phase 0 packet. The fallback (a gateway with an overridden root) would import credential-bearing modules, so I do not recommend it; it would need restating I-1. |
| Licensed-data leakage through screenshots, model context, error text, Collab, fixtures, browser history, Spotlight, crash reports or exports. | Licence breach. | Agent-conduct rule, error mapping, hygiene scanner, synthetic-only fixtures and uisnap screenshots, Private window, `.noindex`, Q-Y14/Q-Y15, exports under `~/betangel-data`. |
| A same-uid agent uses the UI as if it were Yu. | Paper journals with false provenance. | Single-use codes, in-memory token, SSH-side refusals, the conduct rule; I-8 stated honestly as a code-path property. |
| Lab-served JS in Yu's Air browser is buggy or tampered with. | A fake login prompt; credentials typed toward the lab; blind requests to other Air loopback services. | No credential fields ever; Private window; reviewed release copies only; no suite listener on the Air but the `ssh -L` forward during R-2. Summary of 8.6, which has the full text: two checks, both run by Nuance on the Air, a port gate before each `ssh lab-suite` and a loopback inventory that is reviewed, not required to be empty; neither clears the Air's other loopback services, a residual that stays open until a reviewed deny-all content rule exists. |
| Localhost attack surface regresses. | CSRF or rebinding against the paper API. | Security tests on every PR. No live endpoint exists to abuse. The SSH-stdio shell before any live click. |
| The viewer key's residual capabilities are misjudged. | A least-privilege gap on a key Yu adds. | The sshd drop-in (no `-R`, no streamlocal); the Air-side self-test; the forced command runs a release copy; Yu can remove the line at any time. |
| An Air disconnect (lid closed, Wi-Fi blip) during a race. | A spent race or a locked-out session. | Pause unless watched; heartbeat; grace and takeover; `ClientAliveInterval` in the drop-in. A silent disconnect is bounded by about 3 min until the 5 s `not_watched` pause lands, before 1b (section 8.6). |
| Lab-Claude cannot see the UI. | Late UI bugs and round trips with Yu. | uisnap from Phase 0; JS logic tests; problem reports and `diagnose` for real-data issues. |
| Real-data-only bugs that agents cannot see. | Slow fixes. | Problem reports (codes only), `diagnose` with code-only checks, Yu describing the shape (real values are not available without Betfair's specific written agreement naming the provider, plus Yu's OK each time; Q-Y9, section 8.7), a generator sized like real markets. |
| Scope creep toward live features or automation. | Policy breach. | The suite's AGENTS.md, closed routes, the OperatorClick test, synthetic-only `TestOrder`, the proposal process, the live v1 shadow badge instead of live features, live code kept out of this repo. |
| Later live-key risks: Betfair forbids read-only use of the live key, with no published detection rules. The delayed key also places real bets, and there is no sandbox. | Deactivation of a non-refundable £499 key; accidental real bets. | G1: ask Betfair Developer Support first. Paper never on live-key data; live-key data only in sessions placing real bets. The Heartbeat API is never used (it cancels all LIMIT bets). |
| Toolchain: Homebrew could change python@3.13. 3.15 must stay frozen. There is no Xcode or Apple ID for the shell. | Breakage or certification conflicts. | Absolute interpreter path; the version is recorded in `session.json`; nobody runs `brew upgrade`; CLT-only Swift with ad-hoc signing (verified by uisnap). |

---

## Appendix A. Corrections applied from review (draft 0.1)

Base: the mvp-ux draft. The following were fixed or grafted in:

1. **INTERNAL_ONLY.** The engine no longer imports `risk` or `capability` (tests/test_betfair_boundaries.py:22). Exposure is computed in suite code on both bases, and `risk.worst_case_market_loss` (whose default is `hedge_credit=False`, risk.py:136) is a test oracle only. (Superseded: Nuance answered Q-N1 that risk is not an oracle either; section 4.2.) One `rx.py` facade, enforced by an AST test.
2. **Sampled stepping removed.** Exact mode is the default whenever orders are pending or open; the clock lags instead of sampling. The reasons: per-step flooring (paper.py:543), and 503 windows raising high-water marks without filling (paper.py:470-482, :552-553).
3. **Clock-stamped snapshots removed from the default path.** Stamping the activation book at A would count the first interval (paper.py:321, :496-503) and break parity. (Draft 0.1 kept an opt-in relaxation at A − 1 ms; draft 0.2 cut it, section 7.5.)
4. **Integer timestamps.** `utc_from_ns` takes an integer only (receipts.py:29-31), so the design always uses `ms * 1_000_000`.
5. **Audit hook and git.** The hook allowed the exact `git -C <dir> rev-parse --is-inside-work-tree` argv during a startup phase, for `validate_config` and `StatePaths` (paths.py:149, :158; config.py:224-236), and is sealed after startup. Since round 6, in Phase 0 the engine refuses that probe (I-5; Nuance's review of PR #2 at 4fa5835, N5-1; 16df724). If validation is wired later, the probe comes back with an exact environment and its own test, as `guard.py`'s limits say (section 3.8).
6. **Launcher.** `-I` implies `-P`, so the launcher uses a script path and appends `sys.path` itself, adds `-S`, and tests run with `-t .` (verified on 3.13 and 3.11).
7. **Viewer key.** It has a forced command (and runs a read-only release copy); a key without `command=` grants a non-interactive shell.
8. **Readability** comes from the head's `files[]` (market_index.py:720-724, :740-741), never from `evaluator_only_outcome`. The catalogue also never reads `provenance.other_sources`, whose `agrees` field is outcome-derived.
9. **Pin.** The deploy-key submodule is replaced by a network-free local clone, with per-file hashes covering `backtest/*.py` (`code_hashes` does not, receipts.py:121-125) and an import-origin assertion.
10. **Real-data parity banned.** `run_paper_replay` materialises every snapshot (paper.py:991-996), so parity runs only on small synthetic fixtures. Sessions with cancels are "parity not checkable" (paper.py:61). The comparison is field by field with refs excluded (paper.py:842-843).
11. **Citations corrected:**
    - KINDS journal.py:80; INTENT_SOURCES :97; REPLAY_STATUS paper.py:62;
    - config paper defaults config.py:65-66;
    - the last-at-pt rule paper.py:896-902; the close lapse paper.py:913-919;
    - the divisor note paper.py:1016;
    - Rule-4 exclusion pnl.py:53-54 and dead heat :55-56 (both reviewers' numbers were off; checked in the file);
    - `spb`/`spl` via `_PRICE_FIELDS` book.py:56, values not snapshotted (book.py:476-492);
    - `snapshot` key types are not refused by the schema (schemas.py:26).
12. **New findings added** in that revision:
    - the PRO TAR is already in `incoming/`, and Nuance plans a separate data root (multi-root support);
    - Nuance's request for R-1;
    - the high-water-mark gap and conservative re-seeding;
    - the yield tracker for lazy, oracle-equal snapshots;
    - verified in-memory bytes (no check-then-use gap);
    - `HTTPServer.server_bind`'s `getfqdn` lookup;
    - Host checks that accept any port on a loopback host name.

## Appendix B. Review round 2 (draft 0.2)

Three reviewers (interfaces, safety, feasibility) raised 51 issues. All majors were applied, and every minor was applied, some in a simpler form. In summary:

- **Paper path.**
  - The cancel split: pre-submit EXECUTABLE records go to `PaperExchange.cancel`, and CANCEL_PENDING records go only to `classify_cancel_report`.
  - Pending orders are withdrawn as SUBMITTING → REFUSED. (Historical: in live-parity mode Nuance's answer to Q-N5 supersedes this; section 7.6.)
  - Activation at CLOSED and at the end of a member.
  - Position-based high-water seeding with no look-ahead.
  - Exact signatures; `open_orders` as a list; `customer_strategy_ref` aligned with V11; indicative commission rounding mirrored.
- **Scope and rulings.**
  - The non-goal V-rules corrected (V9, V6, V0, V5; GB/IE is a catalogue filter).
  - Nuance's three ruling points listed as R-1, R-5 and R-6.
  - The R-7 learning target.
  - No scripted orders on real data.
- **Safety.**
  - Single-use bootstrap codes and an in-memory token.
  - The sshd drop-in closing `-R` and streamlocal.
  - No engine during runs, via an agreed marker.
  - Error mapping at the `rx.py` boundary.
  - Agents never read the ledger.
  - The Air-browser trust boundary.
  - Release copies for Yu.
  - `TMPDIR`/SQLite temp files, `.noindex`, Analytics.
  - Live and Air code kept out of this repo.
  - Betfair key terms for later phases.
- **Feasibility.**
  - Lab-done and review-accepted exits; the Phase 0 packet; viewing from the Air in Phase 0.
  - uisnap instead of Screen Recording; pause unless watched.
  - Problem reports and `diagnose`; the L1 shell on the Air over SSH stdio.
  - Real-data performance figures; BASIC chart mode and the quiet-book relaxation cut.
  - The checkpoint schedule; tighter limits; prefetch under the GIL; fast and heavy test tiers; HTTP/1.1 chunked streaming.

## Appendix C. Nuance's PR #1 review (2026-10-16)

Nuance reviewed this document at daf9c64 from the upstream and data side: one conditional P1, nine P2s and a list of P3s. Yu's rulings are not reopened. Changes to files that the design branch does not have are made on the branches that do: AGENTS.md and `docs/data-handling.md` on phase0/foundation (67524f4, 632dbda), and proposal 002 and the code on the later branches.

- **1 (conditional P1).** The ladder-type condition: sections 0, 7.1, 7.3, 11 and 12, and U-10. Since round 5 (Appendix F), Nuance's BASIC count is recorded (0 of 12,208) and absent is the working case: sections 0, 1.2, 2.1 (the D-5 note), 7.1, 7.3, 11, 12 and 14 (the introduction and U-10). Since round 5 close, Nuance's PRO count is recorded too (0 of 12,208, 2026-10-19), which confirms it: the same sections.
- **2.** Real values in a model context are not available without Betfair's written agreement naming the provider (Q-Y9, confirmed by Yu on 2026-10-17): rule 5, section 8.7, Q-Y9.
- **3.** Rule 5 covers all of `~/betangel-data` and the install salt; deny rules for lab-Claude's file tools, which Yu approved on 2026-10-16; the optional `~/.ignore` not added (lab-Claude's recommendation, accepted by Yu on 2026-10-17): rule 5, sections 9.2 and 9.4, Q-Y9. Since round 5: Read and Edit denied, Grep and Glob unverified, Bash conduct only; the salt is made once and a lost salt is refused, not regenerated; the salt's move is withdrawn (sections 3.7 and 9.2; Appendix F).
- **4.** Headless real-data commands run only reviewed code: sections 8.6, 10 (I-16, I-18) and 12. Since round 5 the route is chosen: the reviewed-code gate, on `refs/remotes/origin/main` after a fetch, or a release copy's merge SHA; the file-descriptor filter is a later option only (Appendix F). Since round 5 close the commit must also be on that ref's first-parent line (Nuance's answer of 2026-10-18).
- **5.** The marker's scope by rule, and `run/realdata.lock`: section 2.3, rule 7, sections 6.8 and 10 (I-17), Q-N3. Since round 5: the lock's name is confirmed, the wrapper's waits read "at least 60 s", the marker is described as a stop request with draining, and Nuance's agreement as built at 823c194, pending two findings, is recorded (Appendix F). Since round 6: Nuance's agreement as built at 52a9edc, on conditions (sections 3.7 and 6.8).
- **6.** Screen capture on the Air, and the line in the Air's CLAUDE.md, approved by Yu on 2026-10-17 and, since round 5, recorded as in (Nuance confirmed it on 2026-10-17): rule 5, sections 2.2.1, 8.6 and 9.4, Q-Y10, and the screenshot row of `docs/data-handling.md`, which now says "on the lab" and covers the Air separately (applied in lab-Claude's round-4 review).
- **7.** Other Air loopback services: sections 8.6, 9.4, 12 (L1) and 16. Summary of 8.6, which has the full text: the port check began as this item, and its port-scoped pass test is Nuance's words of 2026-10-18. Since round 6 there are two checks, both run by Nuance on the Air, a port gate before each `ssh lab-suite` and a loopback inventory that is reviewed, not required to be empty; neither clears the other services (Nuance's N-r5-002-1 and -2; Astra's review of PR #2 at 4fa5835, item 2; Appendix F, Round 6).
- **8.** The silent-disconnect bound, and the 5 s `not_watched` pause owed before 1b: sections 8.6, 10 (I-19), 12 and 16.
- **9.** The governance row for rule documents, adopted by Yu on 2026-10-17 as Nuance recommended, with Nuance's PR #2 addition: sections 2.2.1 and 3.9 (rule 10 included), Q-N12, Q-Y8.
- **10.** Q-Y8 corrected (its UI-only half answered yes by Yu on 2026-10-17), and R-3 and R-7 marked as stated defaults: sections 2.2.1, 3.9 and 15.1.
- **11 (P3).** The Rule-4 cut-off (7.9); the SP tap's terms (6.6); the trial ledger and inspected months (5.3, 5.5); session ids and end statuses (7.10; since round 5, a reason-to-status map and the next-start sweep); partial invariants and the Air viewing gate (0, 12); no data-root read before the root is agreed (5.2); the practice loss limit (7.2; since round 5, the practice stop); the Air-side repo (3.1); "tick-by-tick" (5.1); the Safari clean-up now (8.6, Q-Y11); `research_months_ruling` (3.8); release by merge SHA, silent codes, the checklist as a log and scanned outbound text (8.6, 9.1, 3.9, 5.6); stale I-14 and c2b3b3/c2b3b4 (0, 2.4, 10, 16, Q-Y16).
- **Questions.** Nuance's answers to Q-N4..Q-N11 and Q-N13 are recorded as Nuance's, and Yu can override them (section 15.2).
- **Q-N5, tracked.** Nuance's answer changes how a pending order is cancelled in live-parity mode. Round 5 applies it, with Nuance's answer of 2026-10-17 that STOP is covered and void withdraws: sections 6.4, 7.6, 7.10, 8.2, 8.3, 11 (the 500 ms test split by mode), 12 (the 1b exit) and 13 (Appendix F).

## Appendix D. Nuance's PR #2 review (2026-10-16)

Nuance reviewed PR #2 at 93e26e6, the whole PR from Nuance's side, plus an independent pass on the guard and scanner after Astra's fixes: five P2 code defects (1-5), one P2 in design text (6), and P3s (7-22). The fixes are on this branch. Nuance re-checked them at 823c194 (Nuance's PR #2 re-review, 2026-10-17): items 1, 2, 4, 8, 9, 11, 12, 13, 15, 16, 17, 19 and 22 are resolved, and the root half (item 1) and the marker half (item 6) are agreed as built, pending F4 and F5. The residuals of the other items became that re-review's findings, in Nuance's mapping: items 3 and 18 to F4, 5 to F7, 6 to F5, 7 to F1, 10 to F6, 14 to F12, 20 to F3 and F9, and 21 to F8. Astra re-reviewed the Astra-routed files at 823c194. Round 5 answers both re-reviews on this branch (Appendix F); the column "Where it is fixed" adds its commits.

| Item | What | Where it is fixed | Sections |
|---|---|---|---|
| 1 (P2) | Roots that resolve into `~/betangel-data` were trusted | 62c39c6, 851885a | 3.7 "Placement", I-6; the root half of Q-N3, agreed as built at 823c194 |
| 2 (P2) | `vendor` wrote into the deploy clone through a linked ancestor | e51b469 | 3.5 item 1, I-13 |
| 3 (P2) | Unguarded child processes after `seal()` | 56a2631, 9a8a11b; fresh loads of `_posixsubprocess` and the subinterpreter modules (F4) in ff35218 | 3.2, 4.1, I-5 |
| 4 (P2) | `listen()` on an unbound socket binds 0.0.0.0 | 01f6201 | I-4 |
| 5 (P2) | The scanner missed encoded or late binary data | 50fe1b7, 6149d94; octal literals (F7) in 58e8426 | 5.6, I-9. The `encoded_blob` text criterion (decoded text that another rule flags) is lab-Claude's addition beyond the review's fix text. |
| 6 (P2, design text) | The marker protocol covered engines only | 596d052, 18de53e, fbbc0c3; `run/` protected too in 6aeb1d5 | 6.8, I-17, Q-N3. Agreed as built at 823c194, pending F4 and F5; F5, `lab-runs/` reopened by a linked state root, is fixed in c3b0c61. Nuance agreed that `test`, `uisnap` and `vendor` take no lock, on four conditions (0a3ed65, 8102f99). The wiring on phase0/http and phase0/viewing is owed (section 6.8, "Owed"). |
| 7 | Imports were not held to the closure | 923c1de, 08af945; the deps directory off `sys.path` and the wider AST filter (F1) in 3f86e34 | 3.5 item 4, 4.2, I-13 |
| 8 | Links in deps reached the clone | e4ddc18, 7357273, 0a1c482; the second pre-pass's place corrected (F10) in 9e6dfce's docstring and section 3.5 | 3.5, 4.1 (`backtest.contract`), I-13 |
| 9 | A falsy rng fell back to `secrets` | ec039db | 4.1, 7.3 |
| 10 | `vendor_argv_ok` ignored the child's environment | 816e832 | 3.5 item 1, I-5. Nuance's note for Astra, that `runner_git_ok` passes `DEVELOPER_DIR` (F6), is closed by an exact allowlist in dd95582 (section 10, "The guard's scope"). |
| 11 | The parity oracle cannot run under the test guard | docs only; the stub is owed before 1b | 3.5 item 3, 4.2 |
| 12 | `research_months_ruling` accepted any id | 3f51ae7 | 3.8, 5.3 |
| 13 | No rule protected the real marker | docs; fbbc0c3 tests that the guard keeps every suite mode out of `lab-runs/` | rule 7 (3.9, AGENTS.md) |
| 14 | The salt was unprotected | docs; lab-Claude's file tools deny it (Q-Y9); "never regenerated" made true in code (F12) in 8288c76 | rule 5, 9.2 item 9, AGENTS.md adaptation B, `docs/data-handling.md` |
| 15 | SQLite temp files could leave the roots | 06dba20 | 3.6, I-6 |
| 16 | The ATTACH limit could be raised | 3da0c26 | I-6 |
| 17 | Read-only descriptors changed metadata | 59e2f22 | I-6 |
| 18 | `_ctypes` reached libc without `dlopen` | 886d64b; a dotted `_ctypes` (F4) in ff35218 | I-5 |
| 19 | Clean filters bypassed the staged scan | 526efcb | 5.6, I-9. The rule on a `.gitattributes` line that sets a filter is lab-Claude's addition beyond the review's fix text. |
| 20 | Messages and pushed history were unscanned; in Nuance's words "P2 before Phase 1" | 268d02d; stale tracking refs (F3) in 77271cd. Partial: on the lab only pre-commit is live (F9), so the hooks go live at the Phase 1a entry gate | 5.6, 9.4, I-9, AGENTS.md "Repository hygiene" |
| 21 | `runner_table` missed tables | ebd1038; NFKC reading and wider lead cells (F8) in 1e39931, with both forms read in 99ed70d | 5.6, I-9 |
| 22 | A FIFO at `config.json` or `install-salt` hung | 53239a3; the pin's reads in e4ddc18 | 3.8, 3.5 item 4 |

Nuance's answers to Q-N2 (section 3.5 and the Q-N2 row) and Q-N14 (section 6.8), and Nuance's additions to Q-N3 (sections 3.7, 5.2, 6.8 and the Q-N3 row) and Q-N12 (section 3.9, AGENTS.md and the Q-N12 row), are recorded as Nuance's, and Yu can override them.

## Appendix E. Lab-Claude's round-4 review (2026-10-17)

Lab-Claude's own review of this branch after the round-4 fixes (lenses on the guard and marker, the vendor tool and scanner, and the documents), and its recheck of those fixes, before Nuance's and Astra's re-checks. A finishing review followed (lenses on the guard, the scanner and the documents; rows marked "Finishing review"). Its guard lens did not finish and reports no findings, so the guard has no finishing review. A recheck of the finishing review's fixes found five more low findings (rows marked "Finishing recheck"); the row on 15.1's status labels is lab-Claude's decision on a question the finishing review's refix left open. A review of the guard's paths, layouts and SQLite parts then wrote a regression-test file and ran it against archive copies of this branch. It found five low findings (rows marked "Guard paths"). Lab-Claude found the variants those rows name while fixing them: the review's prototype fixes left them open. A second recheck, of the finishing recheck's and the guard-paths fixes, found three more low findings (rows marked "Second recheck"). Lab-Claude then decided two questions the guard-paths fix had left open (rows marked "Guard-fix question"). Yu's answers of 2026-10-17 then reached this branch with the design branch's record of them (the row marked "Yu's answers"). Round 4b's recheck of phase0/http and phase0/viewing left one low item on this branch, and one of its questions moved a fix down here (rows marked "Round 4b"). Each finding was checked again before it was fixed; each code fix has a test that fails without it.

| Finding | Fix | Sections |
|---|---|---|
| Renaming `run/` moved `realdata.lock` with it, splitting the lock (medium) | 6aeb1d5 | 6.8, I-6, I-17 |
| The scanner followed replace refs and grafts, so a replaced blob or commit passed every scan while git committed and pushed the original (medium) | 783125d | 5.6, I-9 |
| `encoded_blob` missed GIT binary patches, decimal byte lists, `od` output, bytea literals, base64 of base64 and marker-led dumps (medium) | 7085b08; the other encodings are listed as known gaps | 5.6, I-9, `docs/data-handling.md` |
| `runner_table` missed box-drawing, HTML, LaTeX and fullwidth-bar tables, accented names and names in capitals | 00067cd | 5.6, I-9 |
| `--push` cut its input at 1 MiB, dropping later refs | b4c2656 | 5.6, I-9 |
| `secret_value` missed unquoted values after a colon or a space | c5a5576 | 5.6, I-9 |
| Replace refs and grafts in the deploy clone, and the user's git attributes file, reached vendor's git | 7dc20d7 | 3.5 |
| `cli.main` refused `stop` with `run_lock_not_held` on this branch (and `release`, which only phase0/viewing builds, and exempts) | 96d0bcc, for `stop` | 3.6, 6.8, AGENTS.md A and E |
| What phase0/http and phase0/viewing still owe for the lock: `NO_TMPDIR` around the check, an attached `ssh-session`'s hold of about 50 s, the per-command I-17 tests | docs | 6.8 "Owed", I-17 |
| The shared hooks: the main checkout must not gain the four hooks before every live branch has the new scanner | docs | AGENTS.md "Repository hygiene" |
| `docs/data-handling.md`'s screenshot row lacked "on the lab" (Nuance's PR #1 review, item 6) (medium) | 818fb17 | Appendix C item 6 |
| The fail-closed routing row was credited to Nuance, who named no reviewer, and clashed with "a diff no row covers goes to Yu" (medium) | 818fb17; asked of Nuance on 2026-10-17, and moot since Yu's answers of 2026-10-17, which send unnamed files to Yu (the row marked "Yu's answers") | 2.2.1, 3.9, Q-N12, AGENTS.md |
| The design branch said "to be asked of Yu" where this one said "asked of Yu" | a821be4 (merged in 348b7f7) | 3.9, rule 10, Appendix C item 9 |
| Nuance's "merge the four together, or move each fix down" had no answer; #1 still said the guard refuses fork and spawn after `seal()`, and kept `risk` as a test oracle | a821be4 (merged in 348b7f7) | 2.2.1, 3.2, 4.2, 7.7, AGENTS.md |
| The Q-N3 row credited Nuance with a "never-unlinked" lock | 818fb17 | Q-N3 |
| Recheck: a bulleted or commented list of full commit or file hashes was flagged as binary (`encoded_blob`), as a bare list of sha256 lines had been since 6149d94 (low) | 2ae7640; binary data hex-encoded in whole 40- or 64-digit lines is a new known gap | 5.6, I-9, `docs/data-handling.md` |
| Recheck: `_SECRET_LOOSE` and six more patterns took time quadratic or cubic in line length, so one long line could hang every hook (low) | 805356c | 5.6, I-9 |
| A state root the suite cannot write ended a real-data command in a traceback (exit 1), not a refusal (the concurrency lens; still so at the recheck) | c5fe696 (`run_lock_invalid`) | 6.8 |
| Finishing review: string literals were tried again from every quote, so a line holding `\x` and an unclosed literal full of escaped quotes took time quadratic in its length, 16 minutes for 512 KB in every hook (medium) | 1be5dc1 | 5.6, I-9 |
| Finishing review: in a list of hashes the magic and zlib tests looked only at the first byte, and one NUL or 0xFF byte skipped the text test, so data after one real hash line, and text with such a byte, passed (medium) | 287264a | 5.6, I-9, `docs/data-handling.md` |
| Finishing review: images and PDFs, and binary data with no magic however long, passed in the layouts of a list of hashes (low) | b656145: image and document signatures, and a run of more than 64 such lines is binary again; shorter runs of data with no signature stay a known gap | 5.6, I-9 |
| Finishing review: dumps with words after each token, and lists of md5, sha512 or parent-pair hashes, were missing from the known gaps and false positives (low, older than 2ae7640) | docs | 5.6 |
| Finishing review: D-8 put words in quotation marks that Yu did not write (medium, older text) | 34055b4 (merged in 3a23e2a) | 2.1 |
| Finishing review: wording and status slips: D-5's "The MVP needs none" in Yu's decision; 15.1's "asked of you"; the 15.2 openings on Q-N12 and Q-N14; Appendix D's last line; an undated "open" in `errors.py`; "the suite root is agreed" in `docs/data-handling.md`; the README's rule 7; the lock scope in `runmarker.py` and `cli.py` not marked as asked of Nuance; "in their own words" in rule 7 | 34055b4 (merged in 3a23e2a), and docs | 2.1, 3.9, 15.1, 15.2, Appendix D, AGENTS.md, `docs/data-handling.md` |
| Finishing recheck: b656145's 64-line limit held per run, so runs of 64 lines split by a blank line carried any amount of binary data with no signature, and the scanner's comment read as a total bound (low) | 7126190: the lines of all lists of hashes in one file or message count together, each line once (lab-Claude's decision); a decoded run kept a count of its own until bfd2f6a | 5.6, I-9, `docs/data-handling.md` |
| Finishing recheck: UTF-16 text in a list of hashes passed: read with each NUL as a line end, each character was a line of its own (low) | fab0b92 | 5.6, I-9 |
| Finishing recheck: a decoded run under 96 bytes holding a NUL or a byte that is not UTF-8, outside a list of hashes, got neither the binary nor the text test (low, as old as 6149d94) | 53904f8 | 5.6, I-9 |
| Finishing recheck: the known gap named dumps with words after each token, but not text before it, such as a numbered list (low, older text) | docs | 5.6 |
| Finishing recheck: `docs/data-handling.md` did not label `STATE_ROOT_AGREED` staying True as lab-Claude's call, as AGENTS.md A does (low) | docs | `docs/data-handling.md` |
| 15.1's Q-Y3 status and the 2026-10-16 deny-rules status still said "asked of you", where the other status labels name Yu (lab-Claude's decision on the refix's open question) | 47c403e (merged in 76a53c9) | 15.1 |
| Guard paths: `check_placement` read every failed stat as a missing name. With the data home linked behind a directory that could not be searched when `arm()` ran, a state root linked into it through the firmlink or `/.vol` spelling passed in test and vendor mode, and in engine mode with the suite root not agreed, and took writes there once the directory could be searched again (low; the `/.vol` spelling is lab-Claude's variant) | 57fc0c9: a stat that fails for any reason but a missing name is refused (`root_overlaps_data_home`) | 3.7, I-6 |
| Guard paths: with `run/` a link made before `arm()` to a directory in the state root, `realdata.lock` could be removed and that directory renamed, in every mode. A link to a deeper directory, one through the firmlink, and a lock that is itself a link escaped the same way (low; the variants are lab-Claude's) | b0d5c0d: `arm()` refuses a `run/` or lock that is a link (`run_lock_invalid`), as `hold_shared` already did | 3.7, 6.8, I-6, I-17 |
| Guard paths: a `TMPDIR` deeper in a root moved away when a directory between it and the root was renamed, and a link put in that directory's place took `TMPDIR` out of the roots (low) | 8d0955d: every directory between a root and `TMPDIR` is kept in place (`root_replace_refused`) | 3.7, I-6 |
| Guard paths: a `TMPDIR` that was a link in its root (which guard.py's I-2 text allowed) could be removed and replaced by a link to outside the roots. A link to a deeper directory, and a link on a directory between, escaped the same way (low; the variants are lab-Claude's) | 8d0955d: no name from a root down to `TMPDIR` may be a link (`tmpdir_mismatch`), as `cli.main` already required for every command but `stop` and `vendor` | 3.7, I-6 |
| Guard paths: `pin._open_below` followed a link at its tree when the tree was spelt with a final `/`, `/.` or `//`, despite `O_NOFOLLOW` (low, latent: no caller passes such a spelling) | f77cf01: the tree must end in its own name | I-13 |
| Second recheck: 7126190 gave each decoded run a count of its own, so base64 runs that each decoded to a list of up to 64 hashes carried any amount of binary data with no signature, while the scanner's comment, 5.6, `docs/data-handling.md` and the 7126190 row stated a bound per file or message (low) | bfd2f6a: a list of hashes in a decoded run is never exempt | 5.6, I-9, `docs/data-handling.md` |
| Second recheck: past the count, a list of hashes was binary data only from 96 bytes, so lists of two to four lines split by blank lines passed however many there were. The known gaps named only text before or after each token, not the general gap: binary data with no signature in runs of under 96 bytes each, however many (low; the general gap is older than 2ae7640) | bfd2f6a: past the count, a list that holds a NUL or is not UTF-8 is binary data at any length. The general gap is named in 5.6 and the scanner's comment, and the 64-line bound is stated only for lists of hashes | 5.6, I-9 |
| Second recheck: AGENTS.md Phase 0 status A did not name the refusals that 57fc0c9, b0d5c0d and 8d0955d added to `arm()` in every mode, and the hook's comment in `guard._check_write` named a root or `TMPDIR` but not a directory between them (low) | 58c535a | AGENTS.md A |
| Guard-fix question 3: `roots.lies_in` read every failed stat of the deploy clone as "no clone", as `check_placement` did before 57fc0c9. With the clone linked behind a directory that could not be searched, a path linked into it through the firmlink or `/.vol` spelling was judged outside it, and the guard's partial clone check let that argv through in vendor mode (low; lab-Claude's decision; the link-loop variant is lab-Claude's) | 26fb4c4: a stat of the clone that fails for any reason but a missing name is refused (`research_clone_on_path`) | 3.5 item 1, I-13 |
| Guard-fix question 1: only the guard-paths review's five finding tests, adapted, were in the repo, not the rest of its regression-test file (lab-Claude's decision) | d8d939d: `tests/test_guard_paths.py`, its other 24 tests. The five stay in `tests/test_guard.py` and `tests/test_pin.py`, where they cover more than the review's own versions | none: tests only |
| Final recheck: since bfd2f6a a list of hashes in a decoded run, or past the count, was tested with no line starts, so a magic or zlib stream counted only at its first byte and an image or document signature not at all; a list that was valid UTF-8 with no NUL, such as an ASCII PDF on its second line inside a base64 run, passed (low; a regression from bfd2f6a) | 145fa22: every line start of a list read as binary is checked for a signature, media included | 5.6, I-9 |
| Final recheck: 26fb4c4 judged the clone only; `lies_in` still read a failed stat of the path as missing, so a path through a directory with no search permission that held a link into the clone was judged at that directory and found outside it, and the guard's partial clone check let the vendor argv through (low; the path side of guard-fix question 3) | 4ddf966: the path and its resolved text go through `_known_identity` first, as in `check_placement` | 3.5, I-13 |
| Yu's answers: Yu answered on 2026-10-17 ("Lets go with what you recommended for all :)"; section 2.2.1), but this branch's AGENTS.md and `docs/data-handling.md` still said that the governance row, the UI-only half of Q-Y8, Q-Y9 as reworded, the Air's CLAUDE.md line (Q-Y10), the Safari clean-up (Q-Y11) and the optional `~/.ignore` were asked of Yu, not answered, and the fail-closed row still sent files that no row names to Astra and Nuance jointly | 9d05d8c merges the design branch's record (06440d0) and resolves 2.2.1, 3.9, Q-N12 and Appendix C item 6. Then AGENTS.md: the governance row and the UI-only rule as binding rows, UI-only as lab-Claude's reading; the fail-closed row to Yu; PRs that change AGENTS.md's rules or routing (#2, #4 and #5) wait for Yu's approval of those changes; lab-Claude's test-file row asked of Yu, not answered; rule 5's exceptions, rule 10, the Air's CLAUDE.md line (Nuance adds it) and the Safari clean-up (agreed; Yu to do) as answered. `docs/data-handling.md`: "Exceptions", the screenshot and browser rows, and the deny rules, with `~/.ignore` not added | 2.2.1, 3.9, Q-N12, Appendix C item 6, AGENTS.md (rules 5 and 10, lab constraints, routing), `docs/data-handling.md` |
| Round 4b: `cli.py`'s comment that `test`, `uisnap` and `vendor` "touch neither" claimed more than the guard refused then, and `runmarker.py` gave the wrapper's wait as "waiting 60 s or more" (low; round 4b's recheck, item 2(b)) | f5878a5, after 0a3ed65 made the guard refuse reads in their modes; the wait in the one sentence Nuance's re-review of #2 asks for | 6.8 |
| Round 4b question: the writer helper's `_make_dir` refused a directory another process made between its checks (`path_denied:already_exists`), which made phase0/viewing's SignalTests run flaky (low) | 71574cf: viewing's 68a4b46 moved down, the same change and test (lab-Claude's decision) | none: `roots.py` only |

## Appendix F. Round 5 (2026-10-17)

Round 5 answers Astra's review of PR #1 at 47c403e (items 1-13) and Nuance's re-review of PR #1 at 47c403e (findings 1-15). It also records, as they bear on this document, Nuance's re-review of PR #2 at 823c194: Nuance's answers to lab-Claude's nine questions of 2026-10-17, and the 60 s wording. Astra's re-review of PR #2 and the code findings of both PR #2 re-reviews are answered on phase0/foundation; so are Appendices D and E, and AGENTS.md, whose rules 5 and 7 and routing table this document mirrors. On phase0/foundation, the two tables after Nuance's answers below map them to this branch's round-5 commits. Decisions marked lab-Claude's are lab-Claude's own. Nuance's and Astra's words are quoted as theirs. Yu's words are quoted exactly and never altered or attributed to anyone else; the quotes of Yu that round 5 adds are ones section 2.2.1 records (those that round 5 close adds are Yu's words as relayed by Nuance, labelled so), and older exact quotes of Yu elsewhere (such as "Basic 2%", D-8's words on the £499 key and "learn ladder trading") stay as they were (lab-Claude's call, narrowing an earlier wording of this aim; Round 5 finish, below).

**Astra's PR #1 review**

| Item | What changed | Sections |
|---|---|---|
| 1 (P3): the routing documents disagree | 3.9 carries phase0/foundation's routing rows, which match AGENTS.md's table (the binding copy), with the proposal labels kept; the routing line after the invariants table matches. Who judges a change of meaning: the governance row Yu adopted on 2026-10-17 (Nuance and Astra each, else Yu) | 2.2.1, 3.9, 10 |
| 2 (P2): I-8 leaves no path for cleanup | The system-stop proposal: `PaperDesk.stop_all(SystemStop)`, with no targets and no place, its own reasons, and tests for `bin/suite stop`, expiry, failure and recovery that fabricate no click. Asked of Nuance and Astra in the round-5 replies, not answered | 7.1, 7.6, 7.10, 10 (I-8), 11, 12 |
| 3 (P2): the guard's stated guarantee | Scoped to the audited and wrapped calls; argv shapes, not single uses; the engine, vendor and test modes; the rule against worker processes stays a rule | 3.1, 3.2, 10 (I-3, I-5, I-6, "The guard's scope") |
| 4 (P2): the marker is a stop request | Draining after the marker appears, the wrapper's locks keeping the upstream run apart, and no claim that polling stops every write | 3.9 (rule 7), 6.8, 9.4, 10 (I-17) |
| 5 (P2): vendor's documented entry | Code on phase0/foundation (lab-Claude's decision): run directly, the tool refuses with `launcher_required` (9e6dfce). Here: `bin/suite vendor` is the documented entry, and the launcher example gains vendor's TMP branch and `--py311` | 3.5 item 1, 3.6 |
| 6 (P2): I-9 and the scanner | Bounded pattern detection, with its gaps named and provenance review required; a clean scan is not proof | 5.6, 9.4, 10 (I-9) |
| 7 (P3): the pre-commit hook | It runs the hygiene scan only; the fast tier is its own step | 11 |
| 8 (P3): control clients and I-3 | The control-client exception, tied to its code and tests on phase0/http | 9.1, 10 (I-3) |
| 9 (P3): the salt | Code on phase0/foundation (lab-Claude's decision): first provisioning writes a `salt-provisioned` marker, and a lost salt is then refused (`salt_missing`), never regenerated (8288c76). Here: that text, and the move withdrawn | 3.7, 9.2 |
| 10 (P3): two headless routes | The reviewed-code gate, on `refs/remotes/origin/main`, is chosen; the file-descriptor filter is a later option only | 8.6, 10 (I-16, I-18), 12 (1a) |
| 11 (P3): the oracle recipe | phase0/foundation's correction: no temporary clone; the `paper.git_state` stub is owed before 1b | 3.5 item 3, 4.2 |
| 12 (P3): exact contracts | `urllib.parse` on 3.11; no `SystemClock`; this document's 2 MiB exemption; no traceback file in Phase 0; a code is live until it is redeemed or 120 s have passed | 3.7, 4.1, 5.5, 5.6, 9.1, 9.2 |
| 13 (P3): superseded and open text | Withdrawal rewritten by mode, with draft 0.2's text marked superseded; one ledger field list; the Phase 0 exit names the rulings it needs; Q-Y1, Q-Y2 and Q-Y4 point to their answers | 5.5, 6.4, 7.6, 8.2, 8.3, 11, 12, 13, 15.1, Appendix B |

**Nuance's PR #1 re-review**

| Finding | What changed | Sections |
|---|---|---|
| 1 (P2): STOP's paths cannot hold an OperatorClick | As Astra's item 2, in the shape Nuance prefers; asked of Nuance and Astra | 7.1, 7.6, 7.10, 10 (I-8) |
| 2 (P2): the salt is regenerated | As Astra's item 9. Nuance's answer 4 (do not move it) is accepted | 3.7, 9.2 |
| 3 (P2): UI-only and the no-automation rule | Narrowing UI-only, and the test-file row in Nuance's mechanical form: asked of Yu on 2026-10-17, with lab-Claude's recommendation of yes to both, and answered yes by Yu later that day (Round 5 finish, below). The node tests are owed, and 9.4 gains a residual | 2.2.1, 3.9, 8.3, 9.4, 11, Q-N12, Q-Y8 |
| 4 (P3): stale statuses | Whose recommendation each answered question carried, as lab-Claude's reading; the UI-only recommendation; R-3 and R-7 still open; the Safari clean-up not confirmed done; the Air's CLAUDE.md line is in | 2.2.1, 8.6, 9.4, Q-Y10, Q-Y11, Appendix C |
| 5 (P3): the ladder count | 0 of 12,208 BASIC markets, with its scope; absent is the working case (lab-Claude's decision): U-10 and any D-5 question start now, and M-PRO confirms; the keyless variant is required (f23ba3f) | 0, 1.2, 2.1, 7.1, 7.3, 11, 12, 14 (introduction, U-10), Appendix C |
| 6 (P3): Grep and Glob | `claude --version` is 2.1.301 on the lab; Read and Edit denied, Grep and Glob unverified, Bash conduct only | 2.2.1, 3.9 (rule 5), 9.4, Q-Y9 |
| 7 (P3): the Air's listener | During R-2 the `ssh -L` forward is the only suite listener on the Air; a netstat check before `ssh lab-suite`, by Nuance: proposed, asked of Nuance | 8.6, 9.4, 16, Appendix C |
| 8 (P3): Q-N5 | In live parity a pending order activates, then is cancelled, by one code path, STOP stepping the reader and exchange to A; exploration mode and void withdraw; the freeze wins; the 500 ms test is split by mode; tracked in the 1b exit | 6.4, 7.6, 7.10, 8.2, 8.3, 11, 12, 13, Q-N5, Appendix B, Appendix C |
| 9 (P3): end statuses and recovery | A reason-to-status map with SIGHUP and the marker mapped and no `operator_` reason for a system end; the next-start sweep on Nuance's conditions (answer 6) | 3.7, 6.8, 7.10, 11, 12 |
| 10 (P3): the practice limit | The practice stop: the UTC day, each session's UTC start, the official net or the worst case, checked before the click, failing closed; an R10 line on the shadow badge | 7.2, 7.10, 8.2, 11, 12, Q-Y6 |
| 11 (P3): the ledger fields | Rewritten to Q-N11's, with no market id in the clear | 5.5 |
| 12 (P3): the data-root gate | Nuance's recorded agreement is the gate; the 1a reader also refuses while the flag is False, tested | 5.2, 12 (1a) |
| 13 (P3): "a commit that main contains" | `refs/remotes/origin/main`, named in full, after a fetch; `release.py` the same; it stops accidents, not same-uid rewrites; the first-parent question asked of Nuance | 8.6, 10 (I-16, I-18), 12 (1a) |
| 14 (P3): proposal 001 | The terms' "No onward distribution" clause is cited, and proposal 001 as PR #3, not merged | 8.7, Q-Y9 |
| 15 (P3): slips | The 2.2.1 heading was already fixed; the status line's dates; "agreed marker"; the Q-N1 row answered; python3.11 out of the heavy tier | Status, 0, 3.4, 9.4, 11, Q-N1 |

**Nuance's answers of 2026-10-17** (Nuance's PR #2 re-review, to lab-Claude's nine questions of that day; Yu can override them)

| Question | Nuance's answer, in brief | Where |
|---|---|---|
| 1 | The fail-closed row withdrawn; a test-file row only in a mechanical form, and Yu's to decide | 2.2.1, 3.9, Q-N12 |
| 2 | Agreed, on four conditions: say that the guard refuses only writes, or refuse reads under the real data home; uisnap and `stop` keep modes of their own; a test running when the marker appears is bounded by the per-test and per-module checks | 6.8; 10 (I-6, "The guard's scope"): on phase0/foundation, 0a3ed65 and 8102f99 |
| 3 | `realdata.lock` is the name | 6.8, Q-N3 |
| 4 | Do not move the salt; make "never regenerated" true in code | 9.2 |
| 5 | STOP is covered; void withdraws; the freeze wins | 7.6, Q-N5 |
| 6 | The third withdrawal case agreed, on conditions | 7.10 |
| 7 | Yes, within rule 5; correct "never what is in it" | 3.7 ("Placement"), on phase0/foundation |
| 8 | Both halves of Q-N3 agreed as built at 823c194, pending F4 and F5, on conditions | 2.2.1, 3.7, 3.8, 5.2, 6.8, 12, Q-N3 |
| 9 | No separate store, net across sessions, voided included; the UTC day if the limit mirrors `max_daily_loss`; checked before the click; the amounts are Yu's | 7.2, Q-Y6 |
| The 60 s wording | "At least 60 s", in one sentence for both locks | 6.8, 10 (I-17) |

**Astra's PR #2 re-review** (at 823c194; answered on this branch)

| Item | What changed | Commits and sections |
|---|---|---|
| New finding 1 (P2): a fresh `_posixsubprocess` load restored unguarded child creation | Every fresh load refused once the wrapper is in place (a re-import, `module_from_spec`, `_imp.create_dynamic`, any dotted name), with a dotted `_ctypes`, the subinterpreter modules and `_testcapi`/`_testinternalcapi`; the fresh built-in `posix` module recorded as a same-process residual, beside lab-Claude's probe of a single-phase extension loaded before `arm()` | ff35218, 1617e91; 3.2, 4.1, 10 (I-5, "The guard's scope") |
| New finding 2 (P2): a truncated commit or tag header hid the message from the push scan | A commit or tag object over 1 MiB is refused by its size, before parsing (`object_oversize`), in `--push`; `--range` reads commits only, and refuses a commit over 1 MiB the same way | fbd60fa; 5.6, I-9 |
| New finding 3 (P3): `--message` followed ancestor links | The file is opened a component at a time, no link followed; `/.vol` refused | 35345ba; 5.6, I-9 |
| Judgement: an empty `sys.path` entry | Judged as the cwd | c00461c; 3.5 |
| Judgement: the deps append | Removed | 3f86e34; 3.5, I-13 |
| Judgement: the runner's git environment | An exact allowlist, as vendor's; `DEVELOPER_DIR` refused | dd95582; 10 ("The guard's scope") |
| Judgement: the `uisnap` rationale | `uisnap` and `stop` in modes of their own, never with the suite root | 8102f99; 3.6, 6.8, 10 |
| Judgement: SQLite residuals and scanner limits | Kept as recorded residuals and known gaps | I-6, 5.6 |
| Judgement: governance and the salt | No salt move, so no migration (the move is withdrawn after Nuance's answer 4); the review approves no root agreement or widening, and none is claimed from it | 3.7, 9.2 |
| Six whitespace-only lines in `git diff --check 93e26e6..823c194` | Gone in the merge of the design branch's round 5 (706a6b7) | 6.8, 7.6, 7.10 |

**Nuance's PR #2 re-review** (at 823c194; findings F1-F12, answered on this branch by lab-Claude's round-5 decisions)

| Finding | What changed | Commits and sections |
|---|---|---|
| F1 (P2): the deps directory on `sys.path` | Off `sys.path`; the AST filter flags every name outside the standard library | 3f86e34; 3.4, 3.5 item 4, 3.6, 11, I-13, AGENTS.md C |
| F2 (P2): a test-runner child with the real HOME | The HOME, roots and `TMPDIR` of a launcher child, and since lab-Claude's round-5 review of every interpreter child, checked against the runner's data home at spawn; the whole-checkout scan's child gets a temporary HOME | 96f8a90, 8e751d6; 10 (I-6, "The guard's scope"), AGENTS.md A, `docs/data-handling.md` |
| F3 (P2): pre-push trusted stale tracking refs | Only the old values the remote reports are left out; `git fetch --prune` in the recovery steps | 77271cd; 5.6, I-9, AGENTS.md "Repository hygiene", `docs/data-handling.md` |
| F4 (P2 or P3; the verifiers split): fresh `_posixsubprocess` loads, subinterpreters, a dotted `_ctypes` | As Astra's new finding 1 | ff35218, 1617e91; 3.2, 4.1, I-5 |
| F5 (P3): a state root linked to `~/.local/state` reopened `lab-runs/` | `root_overlaps_lab_runs` in every mode and in the writer helper | c3b0c61; 3.7, 6.8, I-6, I-17, AGENTS.md A and E |
| F6 (P3): `runner_git_ok` accepted any key outside `GIT_*` | As Astra's judgement item | dd95582; 10 |
| F7 (P3): octal-escape literals were not decoded | Decoded from four escapes; the remaining gaps and a false positive listed | 58e8426, 9389c7d; 5.6, I-9 |
| F8 (P3): unusual spaces, fullwidth digits, ignorables and lead cells | NFKC, ignorables dropped; up to three time, date or id lead cells; the remaining gaps listed. Since lab-Claude's round-5 review each text is read as written too, and the lead cells' separator is atomic | 1e39931, 9389c7d, 99ed70d, 1e91dd9; 5.6, I-9 |
| F9 (P3): only pre-commit is live on the lab | Said so; the Phase 1a entry gate (lab-Claude's decision to adopt Nuance's fix) | docs; 5.6, 9.4, I-9, 12, AGENTS.md "Repository hygiene" |
| F10 (P3): where the second vendor pre-pass runs | "after the rename, before the first chmod"; the docstring narrowed | 9e6dfce; 3.5 item 5 |
| F11 (P3): `_in_research` read a failed clone stat as no clone | `roots.lies_in` for the clone and every entry; an empty entry as the cwd | c00461c; 3.5, I-13 |
| F12 (P3): Grep and Glob, `~/.ignore`, the salt | Read and Edit denied, Grep and Glob unverified, Bash conduct only; `~/.ignore` would not have helped; the salt made once and refused when lost | 8288c76; 2.2.1, 9.2, 9.4, Q-Y9, AGENTS.md rule 5 and B, `docs/data-handling.md` |
| The 60 s wording | One sentence for both locks: the wrapper "waits at least 60 s for the lock, then refuses its own run (fails closed) if it is still held" | f5878a5 (comments); 6.8, I-17, Q-N3, AGENTS.md E |
| The vendor ref (Q-N2) | `refs/heads/main` is right; no change | Q-N2, AGENTS.md |

**Open after round 5**

- Asked of Nuance and Astra in the round-5 replies: whether the system-stop proposal widens I-8 (section 7.1). Unless both say it does not, it goes to Yu. Moot under RS-1a since 2026-10-19 (section 2.2.1; Round 6, below).
- Asked of Nuance in the round-5 reply: whether a release must lie on main's first-parent line (section 8.6), and the netstat check before `ssh lab-suite`, by Nuance on the Air (section 8.6). Both answered by Nuance on 2026-10-18 (Round 5 close, below).
- Nuance's agreement of Q-N3, recorded at the merge-candidate SHA once F4 and F5 are dealt with (sections 3.7 and 6.8). On phase0/foundation they are fixed (ff35218, c3b0c61); c3b0c61 changes placement, which by Nuance's condition reopens the re-check (lab-Claude's reading). Agreed by Nuance as built at 52a9edc, on conditions, to be confirmed at the merge SHA (Round 6, below).
- Nuance's and Astra's re-checks of phase0/foundation's round-5 commits (the two tables above, and the tables of round 5's own reviews below), and Yu's approval of its AGENTS.md changes (section 2.2.1).
- The Phase 1a entry gate for the git hooks (section 5.6).
- Nuance's count of the PRO definitions at M-PRO (section 7.1), and U-10. The count is in since 2026-10-19 (Round 5 close, below); U-10 is still owed.
- Yu's: Q-Y6 (the practice stop), R-3 and R-7, and the other open questions in section 15.1. R-3 has Yu's answer as relayed by Nuance on 2026-10-18 (Round 5 close, below), confirmed by Yu on 2026-10-19 (Round 5 confirm, below).

**Round 5's own reviews, design/mvp-draft-0.2** (lab-Claude's four reviews of round 5's commits on the four branches, 2026-10-17; the findings on this branch's text)

| Finding | What changed | Sections |
|---|---|---|
| 3.9's Astra row named neither the launcher's files nor `.gitignore`, which AGENTS.md's table and phase0/foundation's 3.9 name, so read at this branch's SHA a `.gitignore` change went to Yu; this appendix said the rows match (low) | phase0/foundation's Astra row, word for word | 3.9 |
| Text that round 5 made false on PR #2: the deps directory appended to `sys.path` (3.4, 3.5 item 4, 3.6, I-13 and 11), vendor's standalone entry that "refuses under the marker ... or refuses to run standalone" (3.5 item 1 and this appendix's row for Astra's item 5), and the launcher example's TMP case without `stop` (low) | phase0/foundation's wording carried down: the deps directory never on `sys.path` (3f86e34), `launcher_required` (9e6dfce), and `stop` with the state root's `tmp/` (8102f99) | 3.4, 3.5 items 1 and 4, 3.6, 10 (I-13), 11, Appendix F |
| 3.9 quoted its own earlier definition of UI-only with `ui/ticks.json`, which only phase0/foundation's text had (low) | The quote is this branch's own earlier words again | 3.9 |
| The Q-Y9 row quoted words of Yu's that section 2.2.1 does not hold (low) | The quote is dropped; the row says that Yu approved the deny rules on 2026-10-16 | Q-Y9 |

**Round 5's own reviews, phase0/foundation** (the same reviews; the findings on this branch's code and text)

| Finding | What changed | Commits and sections |
|---|---|---|
| D13's check (96f8a90) covered launcher children only. An interpreter child running `-c` code that arms the guard itself, the shape of every engine-policy test child and the one Nuance's F2 reported, was allowed with `env=None` or the runner's own HOME, armed engine mode from that HOME and wrote its suite root (medium) | Every interpreter child, whatever follows `-I -S -B`, and every `bin/suite` child needs an explicit environment whose HOME, roots and `TMPDIR` keep out of the runner's data home; a test child that needs a HOME the runner refuses goes through an unguarded relay | 8e751d6; 10 (I-6, "The guard's scope"), AGENTS.md A, `docs/data-handling.md`, this appendix (F2) |
| One more interpreter option before `_launch.py` (`-X utf8`, `-u`, `-W error`) skipped the launcher check, because only `argv[4]` was read (low) | As above: the check no longer depends on where a script is named | 8e751d6; 10 (I-6) |
| "Never regenerated" was said without its limit in `errors.py`, AGENTS.md B and `docs/data-handling.md`: the marker sits beside the salt, so losing both looks like a fresh install (low) | Each says so, as 9.2 does | docs; 9.2, AGENTS.md B, `docs/data-handling.md` |
| 1e39931's wider lead cells made a row of cells split by runs of tabs take seconds to fail to match, and a file of such rows minutes, in every hook (medium) | An atomic separator after each lead cell; a timing test of 60 such rows | 1e91dd9; 5.6 |
| 1e39931 read only the NFKC form, so a character that NFKC joins onto a token hid base64 and hex runs, provider tokens, ids, member paths and ids in path names that f1c3771 found (medium) | Each text and path read as written and in NFKC form, the findings of both kept | 99ed70d; 5.6 |
| 5.6 said that `--range` reads tag objects; it reads commits only, so a manual range scan never reads an annotated tag's message (low) | 5.6 says so, and AGENTS.md's manual steps feed `--push` a tag's line before it is pushed | docs; 5.6, AGENTS.md "Repository hygiene" |
| Slips: the Q-N3 row's "Nuance agreed" could read as agreeing that `test`, `uisnap` and `vendor` take the lock; AGENTS.md's Safari line left out "not confirmed done"; 6.8 said twice that round 4b "will" make an attached `ssh-session` check the marker on every poll (low) | Nuance agreed that they take none; "and not confirmed done"; round 4b did it on phase0/viewing (e9729a6) | docs; 6.8, Q-N3, AGENTS.md |

**Round 5 finish, design/mvp-draft-0.2** (Yu's two answers of 2026-10-17 that came after round 5's commits, and the low items of lab-Claude's recheck of round 5's fixes)

| Item | What changed | Sections |
|---|---|---|
| Yu's answers of 2026-10-17 to the two questions lab-Claude put that day: the test-file row ("yes lets go with what you recommended") and narrowing UI-only ("ohh understood. Yes lets go with what you recommended") | Both rows are binding, in the form lab-Claude recommended; every "asked of Yu on 2026-10-17, not answered" for them is replaced; the 9.4 residual now rests on review until the node tests exist | 2.2.1, 3.9, 8.3, 9.4, 10, Q-Y8, Q-N12, this appendix |
| Recheck, low item 2: the vendor bullet of "The guard's scope" named only the deps directory, while on phase0/foundation and phase0/http vendor mode may write anywhere in the share directory; only phase0/viewing narrows it (low) | "the share directory `~/.local/share/betangel-suite/` (narrowed to its deps directory on phase0/viewing)" | 10 ("The guard's scope") |
| Recheck, low item 3(c): this appendix said that Yu's words are quoted "only as section 2.2.1 records them", but older exact quotes of Yu stand elsewhere in this document (low) | The aim narrowed (lab-Claude's call): no quote of Yu is altered or misattributed, and new quotes are exact; the older quotes stay | this appendix |

**Round 5 close, design/mvp-draft-0.2** (2026-10-19: Yu's words of 2026-10-18 as relayed by Nuance, and Nuance's mailbox notes of 2026-10-18 and 2026-10-19)

| Item | What changed | Sections |
|---|---|---|
| Yu's words of 2026-10-18, as relayed by Nuance: Q-Y3, "confirm account is basic 2%"; Q-Y11, "Pw deleted too" | R-3 picked, `user_package_verified`, the config default to follow through a reviewed change before Phase 1b; the lab Safari clean-up recorded as done. Each is labelled as Yu's words as relayed by Nuance, with confirmation in Yu's own hand asked of Yu on 2026-10-19. Q-Y17 and Q-Y18 are recorded on phase0/viewing, where they are asked; the relayed UI-only and governance answers repeat Yu's of 2026-10-17 and change nothing | Status, 2.2.1, 3.8, 8.6, 12 (Phase 0), Q-Y3, Q-Y11, this appendix |
| Nuance's M-PRO count (mailbox note of 2026-10-19): `priceLadderDefinition` in 0 of 12,208 PRO markets of 2015-05..2016-04, with the 94 `malformed_runner` markets read only up to the bad definition | Section 7.1's condition holds for BASIC and PRO; U-10, the call-site CLASSIC default and any V9 change going to Yu under D-5 stand; M-PRO's count is no longer owed. The PRO root `historic-pro` is recorded as ingested and indexed (`pro-ingest-01`, 2026-10-19), with its counts; the SP non-finite counts are still owed | 0, 2.1 (the D-5 note), 2.4, 3.1 (the diagram), 3.8, 5.1, 6.6, 7.1, 11, 12 (M-PRO, 1b), 14 (introduction, U-10), 16, Q-N4, Q-Y16, Appendix C |
| The runbook's L1 layout check and the suite root (lab-Claude's question of 2026-10-17): Nuance chose (a) (mailbox note of 2026-10-18) | L1 is to accept `suite.noindex/` and `historic-pro/` as known, optional entries (an upstream change, authored by Astra and reviewed by Nuance, in the next tooling round). Until it lands, no engine command runs with the real HOME (lab-Claude's decision); a risk row | 3.7, 3.8, 12 (1a, M-PRO), 16 |
| The first-parent question (Nuance's answer of 2026-10-18) | Both ancestry and first-parent membership on `refs/remotes/origin/main`, after the operator's fetch, for `release` and for the headless reviewed-code gate (lab-Claude adopts Nuance's answer); the code is for `release.py` on phase0/viewing, with tests | 8.6, 10 (I-16, I-18), 12 (1a), Appendix C |
| The netstat check before R-2 (Nuance's answer of 2026-10-18) | Scoped to the port: `lsof -nP -iTCP:8765 -sTCP:LISTEN` on the Air, nothing on 8765 before the forward and only `ssh` on `127.0.0.1:8765` after it, run by Nuance; the whole-machine wording is dropped; the Air's other loopback services stay a residual until L1's content rule | 8.6, 9.4, 16, Appendix C |

**Round 5 finish and close, phase0/foundation** (cb40c7e and 2b7bd9f from the round 5 finish, 2026-10-17; the rest on 2026-10-19: lab-Claude's recheck of round 5's fixes, AGENTS.md brought in line with Yu's answers, and lab-Claude's answers to the round-5 agents' questions)

| Item | What changed | Commits and sections |
|---|---|---|
| Recheck, low item 1 (Astra-routed): `_check_spawn` judged a collapsed copy of a child's environment, so a bytes HOME or `TMPDIR` placed before a temporary HOME's keys, a `dict` subclass, a bytes network switch or a bytes `GIT_CONFIG_GLOBAL` passed, and the child or git read what the check never saw (low) | The environment is judged item by item, as `subprocess` hands it: one that is not exactly a `dict`, a key that is not exactly a `str`, two keys equal once encoded with `os.fsencode`, or a value that is not exactly a `str` or `bytes` is refused (`subprocess_refused`), for the runner's interpreter children and for the git children of the runner and of `vendor`. Two regression tests, which fail with the old line on 3.13 and 3.11 | cb40c7e; 10 ("The guard's scope"), AGENTS.md A |
| Recheck, low item 3(b): the scanner's usage text listed `(tag <sha> message)` under `--range` (low) | `--push` and `--range` have a line each, and `--range`'s says "commits only"; text only | 2b7bd9f; `tools/hygiene_scan.py` |
| Recheck, low item 3(a): this appendix's row for Astra's new finding 2 put the size refusal of commit and tag objects "in `--push` and `--range`" (low) | A commit or tag object over 1 MiB is refused by its size (`--push`); `--range` reads commits only, and refuses a commit over 1 MiB the same way | docs; this appendix |
| Yu's answers of 2026-10-17 on the test-file row and narrowing UI-only (Round 5 finish, design/mvp-draft-0.2): this branch's AGENTS.md still put both as asked and not answered | Both rows binding in AGENTS.md's routing table, in the form section 3.9 gives: `ui/`'s order-sending paths to Astra, and to Nuance as well for paper-trading keys; `tests/test_ui_assets.py` to Astra; a test file to the reviewers of the modules it imports, else Yu. The fail-closed row no longer holds test files; the node tests owed before 1b and the 9.4 residual are named | docs; AGENTS.md "Review routing and merging" |
| Recheck, low item 2: AGENTS.md A said that `vendor` writes only its deps clone and `pin/` beside the state root, while vendor mode may write anywhere in the share directory on this branch (low) | "the share directory `~/.local/share/betangel-suite/`, narrowed to its deps directory on phase0/viewing" | docs; AGENTS.md A |
| Yu's words of 2026-10-18, as relayed by Nuance (Round 5 close, design/mvp-draft-0.2), in this branch's own documents | AGENTS.md's Safari line: the clean-up done, on "Pw deleted too", with confirmation asked of Yu on 2026-10-19; the relayed UI-only and governance words noted as changing nothing. Rule 6 does not list `release` on this branch and Q-Y18 is asked only on phase0/viewing, so neither changes here; nor does the PRO count, which AGENTS.md and `docs/data-handling.md` do not carry | docs; AGENTS.md (lab constraints, routing) |
| The runbook's L1 layout check (Nuance chose (a); Round 5 close, design/mvp-draft-0.2) | No engine command runs with the real HOME before the widened L1 check lands (lab-Claude's decision) | docs; AGENTS.md A, `docs/data-handling.md` |
| Lab-Claude's answers to the questions the round-5 agents raised | Recorded as lab-Claude's. Kept as labelled proposals: the end-status reason codes (7.10). Lab-Claude's reading, asked of Nuance in the round-5 replies: Esc, Z, X, Shift+Esc and a click on the order cancel a pending order when the replay reaches A while it runs, and STOP steps at once (7.6). Lab-Claude's choice: the practice stop counts the UTC day under both profiles (7.2). The merge sitting waits for Nuance's agreement, recorded at the merge-candidate SHA (2.2.1). Kept as built or as documented: `os.open` with a `dir_fd`, a documented residual (AGENTS.md A); `_testcapi` and `_testinternalcapi` refused (I-5); "around" in `root_overlaps_lab_runs`, as intended; `/.vol` message paths refused as `message_unreadable`; the salt's codes; a broken `~/betangel-research` blocking every start, failing closed; `launcher_required`, and on phase0/viewing `release_not_on_main` and `release_main_missing`; the wording of the Phase 1a entry gate. Accepted: the cost of the full-history scan on a push that creates a ref (5.6). Later options, not built: mapping other scripts' digits (Unicode Nd) to ASCII (5.6's gaps), a defence in depth in `arm()` against inherited variables, and the optional check of the salt's records. c3b0c61 and the other placement and guard changes, cb40c7e among them, reopen Nuance's Q-N3 re-check at the merge-candidate SHA (lab-Claude's reading) | docs; 5.6, 7.6, AGENTS.md A, this appendix |
| The design branch's round 5 close (5d68d7f, 3ccda7a) | Merged; the conflicts in this document resolved on this branch's text | d9af441 |

**Round 5 confirm, design/mvp-draft-0.2** (2026-10-19: Yu's confirmation, in Yu's own hand, of the answers Nuance relayed)

| Item | What changed | Sections |
|---|---|---|
| Yu confirmed the relayed answers in Yu's own hand on 2026-10-19 (Yu's words are quoted in section 2.2.1); they cover Q-Y3 (R-3), Q-Y11, Q-Y17 and Q-Y18 (lab-Claude's reading) | Every place that recorded Yu's confirmation as pending now says the answers were confirmed by Yu in Yu's own hand on 2026-10-19. Q-Y3's and Q-Y11's status cells read "relayed by Nuance; confirmed by Yu 2026-10-19". The quotes stay labelled as Yu's words of 2026-10-18 as relayed by Nuance; section 2.2.1 keeps the rule that a relay is context and adds that the confirmation is why they now count as Yu's answers (issue 2 of lab-Claude's recheck of round 5 close). R-3's config default still changes only through a reviewed change before Phase 1b. Q-Y17 and Q-Y18 are recorded on phase0/viewing | Status, 2.2.1, 3.8, 8.6, 12 (Phase 0), Q-Y3, Q-Y11, this appendix (Open after round 5) |

**Round 5 confirm, phase0/foundation** (2026-10-19: Yu's confirmation of the relayed answers in this branch's own documents, and two nits from lab-Claude's recheck of round 5 close)

| Item | What changed | Commits and sections |
|---|---|---|
| Yu confirmed the relayed answers in Yu's own hand on 2026-10-19 (Round 5 confirm, design/mvp-draft-0.2), in this branch's own documents | AGENTS.md's Safari line says the clean-up is confirmed by Yu in Yu's own hand on 2026-10-19; nothing else in AGENTS.md, the README or `docs/data-handling.md` recorded the confirmation as pending | docs; AGENTS.md (lab constraints) |
| Recheck nit: AGENTS.md A's sentence on cb40c7e left out the value check | It now lists a value that is not exactly a `str` or `bytes` among what is refused, as cb40c7e built it and this appendix's row for recheck low item 1 says; text only | docs; AGENTS.md A |
| Recheck nit: a line of AGENTS.md A and a line of `docs/data-handling.md` ran past the files' wrap of about 100 columns | Re-wrapped; no wording changed apart from the row above | docs; AGENTS.md A, `docs/data-handling.md` |
| The design branch's round 5 confirm (af960fd) | Merged; the conflicts in this document resolved on this branch's text | dcb73ef |

**Round 6, design/mvp-draft-0.2** (2026-10-19: Astra's and Nuance's reviews of PR #1 at af960fd, both ACCEPT; the listener items of Astra's review of PR #2 at 4fa5835 and Nuance's review of PR #5 at 52a9edc; Nuance's agreement of Q-N3 at 52a9edc; and Yu's confirmation of the trainer drop. Decisions marked lab-Claude's are lab-Claude's own.)

| Item | What changed | Sections |
|---|---|---|
| Astra's review of PR #2 at 4fa5835, item 2 (P2), and Nuance's N-r5-002-1 (review of PR #5 at 52a9edc): round 5's port check dropped the inspection of the Air's other loopback listeners | Two checks, both Nuance's on the Air and neither clearing the residual: the port gate before each `ssh lab-suite`, and a loopback inventory, a review rather than a must-be-empty test, before the first R-2 viewing and whenever the list changes, with a listener that could be driven without authentication going to Yu before viewing. Nuance's text, adapted to each place. The residual stays open until a reviewed deny-all content rule exists | 8.6, 9.4, 16, Appendix C |
| Nuance's N-r5-002-2: run without root, `lsof` sees only the caller's own sockets, and "macOS netstat does not show the owning process" is false for `netstat -anv` | The gate uses `netstat -anv -p tcp` filtered to the port (the command is in 8.6), and the sentence is deleted | 8.6, 9.4, 16, Appendix C |
| Nuance's review of PR #1 at af960fd, F5: the port check's credit | It began as Nuance's PR #1 review, item 7, and its port-scoped pass test is Nuance's words of 2026-10-18, now quoted. Lab-Claude's part is the proposal that Nuance run it on the Air | 8.6, Appendix C |
| Nuance's review of PR #1 at af960fd, F2, and N5-2 on PR #5: nothing fixes the merge method, and a fast-forward would put every interim commit on main's first-parent line | Every PR in the sitting lands with `gh pr merge --merge`, never a fast-forward, rebase-merge, squash or direct push to main (lab-Claude adopts Nuance's fix). Allowing merge commits only in the repository's settings is Yu's: asked, not done | 2.2.1, 3.9 |
| Astra's review of PR #1 at af960fd, item 1 (P3), and Nuance's F1: the size exception widens the rule | "512 KiB"; the exception for this document was asked of Yu on 2026-10-19 (Astra's and Nuance's PR #1 reviews), and Yu approved it that day (the row on Yu's answer, below) | 2.2.1, 5.6 |
| Nuance's review of PR #1 at af960fd, F4: "lands" became ambiguous once 416702f merged | Defined: the lab's betangel-research checkout is at a C0 that includes 416702f (betangel-research PR #28), and no suite command runs between that C0's L1 check and the runbook's 5a | 3.7, 3.8, 12 (1a), 16 |
| Nuance's agreement of Q-N3 (Nuance's review of PR #5 at 52a9edc) | Both halves agreed as built at 52a9edc, on conditions (a) to (d), quoted as Nuance's. Under (a), a later fix that touches the Q-N3 file set reopens only its own diff, and Nuance confirms the agreement at the merge SHA in one line | 2.2.1, 3.7, 3.8, 5.2, 6.8, 12 (Phase 0), Q-N3, Appendix C, this appendix |
| Yu's confirmation of the trainer drop on 2026-10-19 ("confirm trainer drop and also manual live order tools"), and Nuance's and Astra's view that two round-5 questions are trainer-only | The system-stop question (I-8) and the cancel timing of 7.6 are recorded as moot under RS-1a of proposal 003 (lab-Claude's decision); both stay labelled proposals. The agent loop's own stop and recovery contract is owed in proposal 003 | 2.2.1, 7.1, 10 (I-8), this appendix |
| Nuance's review of PR #1 at af960fd, F3: the wrapper's locks | No change here: Nuance will change Nuance's wrappers to match section 6.8 (Nuance's condition (d), section 3.7) | none |
| Yu's answer of 2026-10-19 on this document's size, in the lab session and in Yu's own hand: "Yes, approved"; earlier that day, relayed by Nuance from Yu's chat: "design.md increase批准 :)" | The exception for this document is approved by Yu: up to 2 MiB, still content-scanned, and every change to it reviewed by Nuance and Astra; every other file stays under 512 KiB. Section 2.2.1 records Yu's words, the question they answer and the relay. The "asked of Yu" labels for it are gone, and so is the fallback of moving Appendices B, C and F to a file of their own. Allowing merge commits only in the repository's settings is still asked of Yu | Status, 2.2.1, 5.6, this appendix |
| Lab-Claude's recheck of round 6 (P3): 9.4's row, section 16's risk row and Appendix C item 7 restated 8.6's listener text in other words, and 8.6 said "cancels" where Nuance's N-r5-002-1 says "cancelled" | 9.4's row, section 16's risk row and Appendix C item 7 are short summaries, each labelled "summary of 8.6, which has the full text". In 8.6 the item's last sentence is Nuance's, with Nuance's word "cancelled" | 8.6, 9.4, 16, Appendix C |
| A question from round 6's fix work: should the headless reviewed-code gate also require a merge commit? | Yes (lab-Claude's decision): when the gate is built (1a), it also requires that `<sha>^2` names a commit, alongside ancestry and first-parent membership, and its tests add a commit with no second parent | 8.6 |

**Round 6, phase0/foundation** (2026-10-19: the code findings of Astra's review of PR #2 at 4fa5835 and of Nuance's at the same head, which Nuance routed to Astra or confirmed; and this branch's own documents)

| Item | What changed | Commits and sections |
|---|---|---|
| Astra's review of PR #2 at 4fa5835, item 1 (P2): extension aliases restored unguarded children. `-` for `_` (CPython reads each `-` as `_` when it finds the init function) loaded `_posixsubprocess` with the unwrapped `fork_exec` after `arm()` and `seal()`, in every mode, on both interpreters; 3.11 also loaded a name with a NUL after it; the `_ctypes`, subinterpreter and test-module aliases got through too, before and after arming | The hook refuses every import name with a NUL in it and reads the last part of the name as CPython does, `-` as `_`, before comparing it with the refused extensions; `arm()`'s screening of `sys.modules` uses the same check. Tests: the `-`, bare `-` and NUL spellings of `_posixsubprocess`, `_ctypes`, the subinterpreter module and both test modules, before and after `seal()`, in every mode, and the aliases loaded before arming. Fail-before shown on 3.13 and 3.11 (on 3.13 the NUL spelling is refused by CPython itself, with ValueError, before any import event) | 68a40e5; I-5 |
| Nuance's N5-1 (Astra-routed; P2 or P3): the engine-mode git probe ran with any environment; with `DEVELOPER_DIR` it ran a planted `xcrun`, and with `GIT_TRACE` it wrote a file outside the roots | No Phase 0 path runs the probe (checked on this branch, phase0/http and phase0/viewing: `validate_config`, `StatePaths` and `is_inside_git_worktree` have no caller in suite code), so `engine_argv_ok` no longer accepts it. The gap that stays, named in `guard.py`'s limits and I-5: engine mode judges a child's argv, not its environment. An engine-mode twin of the test runner's `DEVELOPER_DIR` test, and the older engine tests now expect the probe refused. Fail-before shown on 3.13 and 3.11 | 16df724; I-5, 10 ("The guard's scope") |
| Nuance's N5-3 (P3): run from cwd=HOME, `bin/suite test -k test_roots` gave 10 errors, because the guard judges a `dir_fd`-relative name against the cwd | `cli._test` changes to its `TMPDIR` before the tests run. A test runs a nested `bin/suite test` from a temporary HOME, as `run_suite` does, whose probe removes a tree holding a `betangel-data/`. The cwd dependence is noted beside the `dir_fd` limit. The launcher's marker order is untouched. Fail-before shown on 3.13 and 3.11 | 198bc38; I-6, AGENTS.md A |
| Nuance's N3-S1 (P3): comments in `runmarker.py`, `cli.py` and `roots.py` said Nuance's answers to lab-Claude's questions 2 and 8 were not answered | Each points to where the answers are recorded (AGENTS.md A and E, DESIGN.md 3.7 and 6.8). Comments only, which by Nuance's condition (a) does not reopen Q-N3 | `runmarker.py`, `cli.py`, `roots.py` |
| Nuance's agreement of Q-N3 at 52a9edc, in this branch's own documents | AGENTS.md A quotes the four conditions; A, E, Merging and `docs/data-handling.md` record the agreement, to be confirmed at the merge SHA | AGENTS.md A, E and Merging; `docs/data-handling.md` |
| Merge commits only, KiB and "lands", in this branch's own documents | AGENTS.md Merging requires `gh pr merge --merge`; `docs/data-handling.md`'s size cell marked the exception for this document as asked of Yu, until Yu approved it (below); AGENTS.md A and `docs/data-handling.md` define "lands" as section 3.7 does | AGENTS.md; `docs/data-handling.md` |
| The cancel timing of 7.6, which only this branch's text carries | Recorded as moot under RS-1a of proposal 003 (section 2.2.1) | 7.6 |
| The design branch's round 6 (2675253) | Merged; the conflicts in this document resolved on this branch's text | f0fe411 |
| The design branch's round 6 close (231e785) | Merged; the conflicts in this document (the status line, 5.6's file types, and Appendix C items 6 and 7) resolved on this branch's text with the same change applied | a640ee1 |
| Yu's approval of this document's size exception (section 2.2.1), in this branch's own documents | `docs/data-handling.md`'s size cell: the exception for DESIGN.md is approved by Yu, up to 2 MiB, still content-scanned, and every change to it reviewed by Nuance and Astra; every other file stays under 512 KiB. Its "asked of Yu" label is gone. AGENTS.md has no size text | `docs/data-handling.md` |
| Lab-Claude's recheck of round 6 (P3): 3.8's "Git calls during validation" and Appendix A item 5, "Audit hook and git", still said that the startup phase allows the git probe | Both say that in Phase 0 the engine refuses the probe (I-5; Nuance's N5-1, 16df724), and that if validation is wired later, the probe comes back with an exact environment and its own test, as `guard.py`'s limits say | 3.8, Appendix A |

**Open after round 6**

- Yu's: allowing merge commits only in the repository's settings (section 3.9), asked on 2026-10-19. The size exception for this document, asked the same day, was approved by Yu that day (section 2.2.1).
- Nuance's: the one-line confirmation of Q-N3 at the merge SHA (section 3.7), and Nuance's re-check of this round's listener text, which Nuance will re-check as one diff once it is merged down.
- Proposal 003's: the agent loop's stop and recovery contract, and the Air's loopback-service residual carried forward with no reliance on the cancelled L1 shell (section 8.6).
- On phase0/http and phase0/viewing, when this branch merges into them: their tests that still expect the engine's git probe to run (lab-Claude's reading of those branches at 90adc64 and 52a9edc) change with it.
