# betangel-suite: design (MVP: offline replay and paper trading)

| | |
|---|---|
| Status | Draft 0.2, for review (review round 2 applied; see Appendix B). Yu's Phase 0 rulings recorded 2026-10-15, and Yu's Q-Y8 answer and the Q-Y19 ruling 2026-10-16 (section 2.2.1). Nuance's PR #1 review applied 2026-10-16 (Appendix C), and Nuance's PR #2 review (Appendix D). Synced with the built Phase 0b and 0c code (branch phase0/viewing) on 2026-10-15; see the end of Appendix B. |
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
- **No policy amendment needed, on one condition.** The MVP needs no amendment to trading policy and no change to betangel-research, provided the PRO market definitions carry `priceLadderDefinition` (Nuance counts this; section 7.1). If they do not, V9 refuses every real paper click, and Phase 1b then also needs Nuance's U-10 and any V9 change Yu rules on under D-5.
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
- **No changes elsewhere.** Nothing in betangel-research changes, and none of Yu's trading policies change (subject to section 7.1's ladder-type condition).

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

*Lab-Claude's note on D-5, not part of Yu's decision:* the MVP needs no policy change, subject to section 7.1's ladder-type condition. If the PRO definitions lack `priceLadderDefinition`, Phase 1b also needs Nuance's U-10 and any V9 change Yu rules on under D-5.

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

#### 2.2.1 Yu's answers (2026-10-15; Q-Y19 2026-10-16)

Yu, in the lab session: "bet angel never used. Lets go with what you recommended for all."

| ID | Ruling |
|---|---|
| R-1 | **Yes.** The suite drives `paper.PaperExchange` directly with its own paper journal, outside `gateway.py`, for paper orders Yu clicks on historical replay. |
| R-2 | **Yes.** Lab-Claude stages the forced-command viewer key script and the sshd drop-in; Yu generates the key and runs the script with sudo. |
| R-3 | **Stated default (the packet made no recommendation; Yu has not picked).** `user_package_unverified` until Yu checks the package in My Account. Lab-Claude reads "Lets go with what you recommended for all" as leaving this default in place (lab-Claude's reading, not Yu's words). The choice stays open (Q-Y3). |
| R-4 | **Agreed by Yu.** `~/betangel-data/suite.noindex`. Nuance agreed it on three conditions in Nuance's PR #4 review, and `roots.STATE_ROOT_AGREED` was then set True (section 3.7). Nuance's PR #2 review makes that agreement conditional again, on Nuance's PR #2 item 1 (Q-N3). That item is fixed on this branch (62c39c6, 851885a); its re-check was asked of Nuance on 2026-10-17, not answered. |
| R-5 | **Yes.** A suite-side, display-only SP parser; no `schemas.py` change. Nuance confirmed it on the terms in section 6.6 (Q-N9, PR #1 review, 2026-10-16). |
| R-6 | **Confirmed.** No rule-generated paper orders in the MVP. Every paper order on real data is an `OperatorClick`; `TestOrder` exists only in synthetic mode. |
| R-7 | **Stated default (the packet made no recommendation; Yu has not picked): practise live v1** (`v1-live-mirror` caps, live-parity mode). The packet left the choice to Yu. Lab-Claude reads "Lets go with what you recommended for all" as leaving this default in place (lab-Claude's reading, not Yu's words). The choice stays open, and the `practice` profile is still built and selectable. |

**Q-Y8, who merges: not one of the 2026-10-15 answers.** An earlier version of this table listed a Q-Y8 row here: lab-Claude merges after the routed reviewer accepts, UI-only PRs merge on Yu's acceptance alone, and "Yu can veto or revert any merge". That row is withdrawn. Nuance found no source for its merge half or for "Yu can veto or revert any merge" (PR #1 review, item 10). Nuance pointed to section 3.9's recommendation (UI-only PRs need only Yu's acceptance) as the source of the UI-only half.

- **The packet's line:** "Who merges pull requests (Q-Y8): you, or me after Nuance or Astra has reviewed? And may UI-only changes go in on your approval alone?" It gave no recommendation, so "Lets go with what you recommended for all" did not answer it.
- **Yu's answer** (2026-10-16, in the lab session): "Its all good :) Merge when sensible".
- **Lab-Claude's reading of "sensible"** (lab-Claude's, not Yu's words; Yu can override it):
  - lab-Claude merges a PR only when every reviewer routed to it in section 3.9 has accepted the same head SHA, and the tests pass on 3.13 and 3.11 at that SHA;
  - until Yu rules on the governance row (section 3.9), a PR that touches a rule document waits for both Nuance and Astra to accept the same head SHA (Nuance's recommendation). Every other file has a row, the fail-closed row included (section 3.9), so no diff is left for Yu by default;
  - PR #5 also waits for Yu's written approval of proposal 002 (on phase0/viewing), after Nuance's and Astra's reviews of it;
  - the merge order is lab-Claude's decision: #1, #2, #4 and #5 merge in one sitting, in that order, with nothing merged in between, each accepted at its head SHA, after Yu's written approval of proposal 002. That is the option Nuance offered, "merge the four together". Some fixes exist only on a later branch and correct text that an earlier PR still carries (f931637, ab766a0 and 0c1335b, on #5; Nuance's PR #1 review, P3: "merge the four together, or move each fix down"). Stale text that can stand on its own is also moved down to the earliest branch that carries it, as 3.2's fork-and-spawn sentence and the `risk` oracle rows (sections 4.2 and 7.7) were moved to #1.
- **The UI-only half: asked of Yu in the packet and again on 2026-10-17, not answered.** Lab-Claude's reason for treating it as open, although Nuance points to section 3.9 as its source: the packet, the page Yu answered, put it to Yu as an open question with no recommendation, and Yu's 2026-10-16 answer does not take it up separately. Section 3.9's UI-only rule stays a proposal until Yu answers.

**Bet Angel on Yu's Betfair account:** never used (Yu, 2026-10-15), so the design needs no handling for orders or limits shared with Bet Angel. If Bet Angel is ever installed against the account, that needs a fresh review first.

**Q-Y19, Air-side files in this repo** (Yu, 2026-10-16, in the lab session: "Go for D"). Option D records that the R-2 approval already covered the two Air files of section 8.6 item 2, `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`, and rewords rule 1 so its network clause does not cover them (section 3.9, AGENTS.md). Option D's text noted that rewording a binding rule may still need the rule 10 proposal process. Lab-Claude read D, as its text says, as a clarification rather than a widening. So it drafted no `docs/proposals/` file at first. It asked Yu whether one was wanted. Yu answered the same day, in the lab session: "yes to formal proposal". That file is `docs/proposals/002-air-viewer-files.md` (proposal 002). It is a draft for review by Nuance (Q-N15) and Astra. Yu is then asked to approve the reviewed proposal in writing. The reworded rule is also reviewed with PR #5. PR #5 does not merge before Yu's written approval of the reviewed proposal 002 (lab-Claude's commitment, not Yu's words; proposal 002, section 9).

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
  - Nuance will ingest it into a separate data root, `~/betangel-data/historic-pro`, so that P0's BASIC input descriptor stays unchanged. There is no date yet (Q-N4). Nuance asked that `data.tar` and `incoming/` be left as they are.
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
 |   (~/betangel-data/historic-pro once named)     |
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
   - **Air and live code.** This lives in a separate repo under Yu's account, never in betangel-research, which is cloned on the lab (Nuance, Q-N13). That repo is **never cloned on the lab**. It uses its own entrypoint package, which the lab's AST and import tests forbid. `guard.py` has no off-switch: no environment variable or config flag disables it, so nothing in this repo can run with the network on.

### 3.2 Threads

- **Actor thread.** Owns all mutable state: the catalogue handle, the open market replay, clock, yield tracker, traded high-water tracker, checkpoints, paper desk, journal and folder. Every command arrives on one `queue.Queue`, so book and paper state need no locks. It ticks every 20-50 ms of wall time.
- **Loader thread.** Builds the catalogue and prescans the market being opened.
  - It prefetches the next race at the same meeting **only in display mode or while paused**. It works in chunks of about 2,000 lines, yields between chunks, and stops when an actor tick overruns.
  - The reason: python3.13 has the GIL. Prescan is pure-Python parse and apply (about 0.75 s of CPU for a median member and about 6 s for the largest), so running it during exact mode adds lag and jitter.
  - A worker process is not an option. After `seal()` the guard refuses every way to start one. In every phase it also refuses a direct `_posixsubprocess.fork_exec`, and importing `multiprocessing` or `concurrent.futures.process`: these start children with no audit event of their own (I-5; Nuance's PR #2 review, item 3, found the old "refuses fork and spawn after `seal()`" false for them; 56a2631).
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
  guard.py                    audit hook (startup phase, then sealed; modes engine, test, vendor, release, uisnap), environment refusals; stdlib only; no off-switch
  pin.py                      deps checkout lookup, per-file hash check, sys.path append, origin assertion, closure finder, read_pinned
  rx.py                       THE ONLY module that imports betangel_research (section 4); maps upstream errors to codes
  roots.py                    state roots, the single writer helper (O_EXCL|O_NOFOLLOW, 0600/0700)
  release.py                  bin/suite release, and the RELEASE.json check at every launch from a copy (I-18)
  runmarker.py                the run marker and the real-data lock (section 6.8)
  errors.py                   closed error-code enum, salted identifier hashes, excepthooks
  config.py                   suite config, cap profiles, repo validate_config call
  engine.py                   Phase 0: the actor, clock and frames for one synthetic market (replay/ later)
  synthetic.py                Phase 0: the synthetic market generator (reserved namespace)
  uisnap.py                   bin/suite uisnap (section 11)
  data/      discover.py catalogue.py member.py reader.py roles.py ledger.py
  replay/    clock.py tracker.py checkpoints.py tap.py hwm.py frames.py budget.py
  paper/     desk.py click.py pending.py exposure.py greening.py rule4.py queuetrack.py session.py report.py
  api/       server.py auth.py routes.py stream.py static.py control.py
             lifetime.py (pause unless watched: viewer generations, grace, maximum time) sshsession.py (bin/suite ssh-session)
  cli.py     serve | open | ssh-session | stop | catalogue | selfcheck | diagnose | ledger-summary | release | test | uisnap | vendor
ui/          index.html app.js ladder.js grid.js keys.js chart.js style.css manifest.json sounds/
ui/tests/    *.test.mjs (node --test with each file named, no npm)
tests/       test_*.py (unittest); fixtures/gen.py (synthetic only, generated into temp dirs)
tools/       vendor_research.py hygiene_scan.py pre-commit commit-msg pre-merge-commit pre-push
             export_ticks.py (writes ui/ticks.json from the pinned CLASSIC ladder)
             uisnap/uisnap.swift (section 11)
             stage/ suite-viewer-setup.sh air-viewer-selftest.sh air-ssh-config.snippet suite-alias.zsh README.md (staged for Yu, section 8.6)
docs/        DESIGN.md threat-model.md keymap.md data-handling.md proposals/NNN-*.md
.gitignore   *.bz2 *.tar *.sqlite* *.jsonl exports/ run/ screenshots/ (synthetic ones under docs/synthetic/)
```

The repo root holds no top-level `.py` file; a test enforces this. That matters because discovering tests with `-t .` puts the root on `sys.path`.

**Phase 0 as built.** `data/`, `replay/` and `paper/` do not exist yet: the synthetic replay lives in `engine.py` and `synthetic.py`. `ui/` holds `index.html`, `app.js`, `ladder.js`, `grid.js`, `stream.js`, `format.js`, `style.css`, `manifest.json` and `ticks.json`. The keymap is in `app.js`; there is no `keys.js`, `chart.js` or `sounds/` yet. Of `docs/`, only `DESIGN.md`, `data-handling.md` and `proposals/` exist.

### 3.5 Dependency on betangel-research

The pin is a **read-only, network-free local clone**:

1. `tools/vendor_research.py <full-sha>` (`bin/suite vendor <full-sha>`) is run by hand: by lab-Claude, never automatically. Before any git call or mkdir, it refuses `research_clone_on_path` when the deps root, the pin directory or the checkout lies in `~/betangel-research`. The check is by name or by identity (`st_dev`/`st_ino`), at the nearest existing ancestor, so a link spelled through the firmlink is seen too. It is repeated just before the clone, and the guard refuses a partial clone path in the clone as well (Nuance's PR #2 review, item 2; e51b469). A clone that cannot be stat()ed for any reason but a missing name (no search permission, a link loop) cannot be judged, and is refused the same way (26fb4c4), and so is a path that cannot be stat()ed for such a reason, such as one through a directory with no search permission that holds a link into the clone (4ddf966). Every git call runs with exactly `guard.VENDOR_GIT_ENV` plus HOME; the guard refuses an inherited or any other environment (item 10; 816e832). That environment turns replace refs and grafts off (`GIT_NO_REPLACE_OBJECTS=1`, `GIT_GRAFT_FILE=/dev/null`): either would make a dangling commit look like an ancestor of main to `merge-base --is-ancestor`. Every call also has `-c core.attributesFile=/dev/null`, so the user's `~/.config/git/attributes`, which `GIT_CONFIG_GLOBAL` does not cover, cannot change the bytes checkout writes and `--bump` pins (lab-Claude's round-4 review; 7dc20d7).
   1. It runs `git -C ~/betangel-research cat-file -e <sha>^{commit}`, a read-only object lookup. If the commit is not there yet, it stops and asks you to wait for the Air's fast-forward. It never fetches. Then `git -C ~/betangel-research merge-base --is-ancestor <sha> refs/heads/main`, also read-only: only a commit on the research main branch can be pinned, otherwise vendor refuses with `commit_not_on_main` (Nuance's PR #2 review, answering Q-N2: "cat-file -e accepted unmerged and dangling commits"; 1d23fdc).
   2. `git clone --no-checkout --no-hardlinks ~/betangel-research ~/.local/share/betangel-suite/deps/betangel-research-<sha12>.partial`, a local clone with no network.
   3. `git -C <dir> checkout --detach <sha>`, then `git -C <dir> remote remove origin`, so no later command can fetch from the moving clone.
   4. Compute the sha256 of every allowlisted file (section 4.1) plus `research/experiments/backtest-p0-bsp-v1.json`, which holds the month roles. Write them into `pin/betangel-research.json` (on a pin bump) or check them against it (on a fresh machine).
   5. Rename the directory into place and `chmod -R a-w` the working tree. Before the pin is hashed (step 4), and again before any chmod and the rename, a pre-pass over the whole tree checks that it is a real directory outside the clone, holding only directories, symlinks and regular files with one link (`deps_link_present`). chmod never follows a link (Nuance's PR #2 review, item 8; 7357273).
2. **Rules.**
   - Never `git worktree add`, which would write into the deploy clone's `.git`.
   - Never a submodule over the deploy key.
   - Never `sys.path` pointing at `~/betangel-research`.
3. **Why a clone and not `git archive`.** A real checkout lets the upstream offline suite run in its native layout on a pin bump: some of its tests check the real checkout only when the tree is one (`support.IN_GIT_CHECKOUT`, for example tests/test_betfair_paths.py:85). Nuance answered Q-N2: "Keep the network-free clone after 2 and 10" (Nuance's PR #2 findings 2 and 10, both fixed: e51b469, 816e832). Either way nothing is written into `~/betangel-research`.
   - **Dropped reason** (Nuance's PR #2 review: "Drop 3.5 item 3's git_state reason (11); keep the upstream IN_GIT_CHECKOUT one"). This item used to say that the clone lets the oracle `run_paper_replay` record a `git_revision` through `receipts.git_state`. Under the test guard, `git_state`'s `GuardRefusal` escapes its `except` (receipts.py:128-146), so the parity test stubs it instead (section 4.2).
4. **At startup.** `pin.py` checks the files against `pin/betangel-research.json` and refuses with `pin_mismatch` if they differ; hashing about 25 files takes a few ms. No git runs at startup. Then:
   - it **appends** the deps directory to `sys.path`; it never inserts at index 0, so the standard library cannot be shadowed;
   - it asserts that `Path(betangel_research.__file__).resolve()` lies inside the deps directory;
   - each pinned file is opened below the deps directory with `O_NOFOLLOW_ANY` through `dir_fd` (a component walk where the flag is missing), with `O_NONBLOCK`, and is refused unless it is a regular file with exactly one link (Nuance's PR #2 review, items 8 and 22; e4ddc18);
   - `activate()` puts a `meta_path` finder first. From then on only the 25 closure modules can be imported from `betangel_research`, only from their pinned files, and only from bytes that match the pin at load time. Any other `betangel_research` name is refused with `upstream_import_refused`, however it is imported (item 7; 08af945). A test checks that the pinned files import only the closure (AST; 923c1de).
   
   `receipts.code_hashes` covers only the package root and `betfair/*.py` (receipts.py:121-125), which is why the suite hashes `backtest/*.py` itself.
5. **Pin bumps.** A bump is a suite PR. It lists the diff of allowlisted files and runs:
   - the contract test (section 4.5). A bump merges only if it passes at the new pin (Q-N1);
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
  test|uisnap|release|vendor) TMP="$HOME/.local/state/betangel-suite/tmp" ;;
  *)                          TMP="$HOME/betangel-data/suite.noindex/tmp" ;;   # created 0700 after the run-marker check
esac
exec /usr/bin/env -i HOME="$HOME" USER="$USER" LANG=en_GB.UTF-8 PATH=/usr/bin:/bin \
  TMPDIR="$TMP" SQLITE_TMPDIR="$TMP" SUITE_VIA_SSH="$VIA_SSH" \
  BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 \
  /opt/homebrew/bin/python3.13 -I -S -B "$ROOT/bin/_launch.py" "$@"
```

- **Phase 0's `bin/suite`** differs from this listing in two ways:
  - it refuses to run with `HOME` unset (`HOME="${HOME:?}"`), and passes `USER="${USER:-}"`;
  - `test --py311` runs `/opt/homebrew/bin/python3.11` instead of python3.13.

  Its `TMP` branches are the listing's, now that `roots.STATE_ROOT_AGREED` is True (AGENTS.md, Phase 0 status A). The commands in the first branch are those whose guard mode never gets the suite root (`roots.STATE_TMP_COMMANDS`).
- **The SSH checks catch accidents, not a determined same-uid process.**
  - The Air agent key is a full shell with no forced command, so `SSH_ORIGINAL_COMMAND` is unset there too.
  - These checks stop `open` or `--print-url` from running over SSH.
  - `ssh-session` accepts `--port N` for tests only (N = 0 picks a free port). The forced command passes no arguments, and an SSH client cannot add any, because a requested command is refused (`refused:ssh_original_command`).
  - The rest rests on the agent-conduct rules (section 3.9, rule 6).
- **Release copies.** `_launch.py` resolves its root with `realpath`, so `app/current` runs exactly one copy. A root under `~/.local/share/betangel-suite/app` must be `app/<sha12>` of the commit its `RELEASE.json` names, and match that `RELEASE.json`, before any command runs, `stop` included (section 8.6); any other root is a working checkout.
- **`-I` and `-S`.**
  - `-I` implies `-P`: neither the script directory nor the cwd is put on `sys.path`. So `_launch.py` appends the repo root itself, and `pin.py` appends the deps clone.
  - `-S` drops Homebrew's `site-packages`, so a stray package there cannot shadow `betangel_suite` or `betangel_research`.
  - The suite and betangel-research are stdlib-only. Upstream checks this for `betfair/*.py` at tests/test_betfair_boundaries.py:297 and for the backtest package at tests/test_betfair_backtest_boundaries.py:949.
- **`env -i`.** Drops any inherited `BETFAIR*`, `BETANGEL_BETFAIR_*`, `PYTHON*` or `SSH_*` variable. Only `HOME`, `USER`, `LANG=en_GB.UTF-8`, `PATH=/usr/bin:/bin`, `TMPDIR`, `SQLITE_TMPDIR`, `SUITE_VIA_SSH`, `BETANGEL_BETFAIR_FORBID_NETWORK=1` and `PYTHONDONTWRITEBYTECODE=1` are set.
- **Temporary files.**
  - `env -i` would otherwise leave `tempfile.gettempdir()` at `/tmp`.
  - Homebrew SQLite 3.54.0 is built with `TEMP_STORE=1`, so large sorts can spill temp files to SQLite's search path. Those would be licensed derivatives outside `~/betangel-data`, opened in C where the audit hook cannot see them.
  - So `TMPDIR` and `SQLITE_TMPDIR` point at a 0700 directory inside the suite root, created only after the run-marker check (section 6.8). `stop`, `vendor` and `release` make no temporary files, so `cli.main` creates none for them (`cli.NO_TMPDIR`; 96d0bcc for `stop`).
  - And the guard's `sqlite3.connect` wrapper sets `temp_store=MEMORY` on every connection, and refuses one where it does not then read 2 (`sqlite_connect_refused`). The hook refuses `connect("")` (`sqlite_connect_refused`), because that private database is itself a temporary file, opened before the setting. Otherwise SQLite would fall back to `/var/tmp` or `/tmp` if `TMPDIR` were gone (Nuance's PR #2 review, item 15; 06dba20).
- **Python 3.13 is primary.** Tests also run on `/opt/homebrew/bin/python3.11`, matching the upstream syntax floor.
  - The engine refuses to start on any other major version, and in particular on 3.15. It is refused because 3.15 is frozen for Nuance's certification, and so that one interpreter (3.13, with 3.11 as the floor) is the tested one.
  - Nothing installs or upgrades an interpreter. `session.json` records the interpreter version.
- **Tests.** `bin/suite test [--py311] [--heavy] [-v] [-k PATTERN] [-j N]` runs `unittest` over `tests/` from the repo root under the same environment. The test modules are spread over N worker interpreters (default 3, at most 4), whole modules each; `-j 1` runs them in the runner itself. The UI's `node:test` files run from `tests/test_ui_assets.py`, which names each `ui/tests/*.test.mjs`, because `node --test ui/tests` (a directory) fails on node 24. Section 11 has the fast and heavy tiers.

### 3.7 State roots (R-4 agreed by Yu; Nuance's agreement, Q-N3, is conditional again since Nuance's PR #2 review)

| Root | Mode | Contents | Licensed? |
|---|---|---|---|
| Indexed data roots, for example `~/betangel-data/historic-pro` (Nuance's, read-only to the suite) | as is | raw, manifests, index | yes |
| `~/betangel-data/suite.noindex/` (the **suite root**) | 0700 | `catalogue/<index_head_sha256>.sqlite`, `sessions/<YYYY>/<MM>/<session_id>/{journal-paper.sqlite, commands.jsonl, session.json, report.json}`, `ledger/viewed-markets.jsonl`, `reports/` (problem reports, codes only), `exports/`, `logs/` (codes and counts only), `private/` (full tracebacks; agents never read it), `tmp/` | derivatives: yes |
| `~/.local/state/betangel-suite/` | 0700 | `config.json`, `prefs.json` (UI preferences only), `install-salt` (0600; Phase 0 adaptation B; section 9.2, item 9), `run/{engine.lock, realdata.lock, engine.pid, STOP, control.sock}`, `tmp/` (the `TMPDIR` of the test runner, `uisnap`, `release` and `vendor`; section 3.6), `uisnap/build/<sha256>/` (the uisnap `swiftc` build, plus a shared `module-cache/` of about 233 MB), `uisnap/out/<UTC stamp>/` (synthetic PNGs and `report.json`) | no |
| `~/.local/share/betangel-suite/deps/betangel-research-<sha12>/` | read-only | pinned upstream code | no |
| `~/.local/share/betangel-suite/app/<sha12>/` + `current` symlink | owner-only read-only: files 0400, executables 0500, directories 0500; `app/` 0700 | the reviewed release copy that every command Yu runs uses; named by the merge commit's first 12 hex digits (lab-Claude's naming; section 8.6) | no |

Phase 0 creates only `run/engine.lock`, `run/realdata.lock` and `run/control.sock` in `run/`: no `engine.pid` or `STOP` yet.

- **Rules for the suite root:**
  - it must pass `archive.check_data_root` (archive.py:273): outside the repo and every worktree;
  - every derived path goes through `path_guard.guard_path` (path_guard.py:58; `prospective=True` for new files), which refuses the repo's live-state and certificate trees. The suite never reads the deny list itself; it uses only `guard_path`, `PathDenied` and `denied_sequence` (path_guard.py:25-27);
  - a single writer helper refuses any write outside the roots above. A directory it is about to make that another suite process makes meanwhile, as when two commands start together in a new HOME and both make the suite root's `tmp/`, is judged as an existing entry: the path guard, then the link, type, owner and mode checks. It is not refused, and a link put there still is (68a4b46, round 4b).
- **Placement** (Nuance's PR #2 review, item 1; 62c39c6, 851885a). The roots check trusts each root's real path, so the file system must not put a root where the text does not say:
  - the suite root must be a real directory, or missing, at exactly `realpath(~/betangel-data)/suite.noindex`. A `suite.noindex` that is a link is refused (`suite_root_misplaced`);
  - every other write root, and `TMPDIR`, must not equal, lie in or contain `~/betangel-data`. This is judged by casefolded realpath and by `(st_dev, st_ino)`, walking ancestors with `..`, both ways, with stat calls only (`root_overlaps_data_home`). A stat that fails for any reason but a missing name cannot be judged, and is refused too (57fc0c9);
  - `guard.arm` checks every write root of the mode and `TMPDIR`; the writer helper checks the root of each path it writes;
  - no name from a root down to `TMPDIR` may be a link (`tmpdir_mismatch`; 8d0955d), nor `run/` or `run/realdata.lock` (`run_lock_invalid`; b0d5c0d), so each is where its text says. Links above a root stay allowed;
  - the hook refuses a symlink, hard link or rename that puts a name where a root, `TMPDIR` or a directory between `TMPDIR` and its root is, or moves one away (`root_replace_refused`; 8d0955d for the directories between);
  - so every `arm()`, the test runner's included, stats the `~/betangel-data` entry itself, never what is in it, and the engine also lstats `suite.noindex`. Whether that stat, and the `(st_dev, st_ino)` ancestor walk, are within rule 5 was asked of Nuance on 2026-10-17, not answered.
- **`run/realdata.lock`** (section 6.8) is made once (0600) and never unlinked. The guard refuses removing, moving or replacing it (`run_lock_protected`; 18de53e), and `arm()` refuses a `run/` or lock that is a link (`run_lock_invalid`; b0d5c0d).
- **Never touched:**
  - `~/betangel-data/lab-state`, `~/betangel-data/logs`, `incoming/`, and anything under a data root for writing;
  - `~/Library/Application Support/betangel-research/betfair` and `~/.config/betangel-research`;
  - the Keychain.
- **Nuance's conditions (Q-N3).** Nuance agreed the suite root on three conditions (PR #4 review, 2026-10-16):
  1. Nuance never uses `~/betangel-data` or `suite.noindex` itself as a data or lab-state root.
  2. Before Phase 1a, the suite refuses a data root that equals, contains or lies inside `suite.noindex`, `lab-state` or `logs`, or that lies inside `incoming/`. It compares roots by file identity, not by path text. **Owed before Phase 1a** (section 5.2); Phase 0 reads no data root.
  3. The marker half is agreed first. Nuance agreed it in the same review; Nuance's PR #2 review makes both halves conditional again (section 6.8; Q-N3).
- **The root half, after Nuance's PR #2 item 1.** Nuance's words: "agree the root half after 1". Item 1 (roots that resolve into `~/betangel-data`) is fixed on this branch by the placement rules above (62c39c6, 851885a). The re-check of the fix was asked of Nuance on 2026-10-17, not answered, so the root half is not agreed again yet. `roots.STATE_ROOT_AGREED` stays True meanwhile. That is lab-Claude's call: with the fix, the engine refuses a misplaced suite root, and no Phase 0 command reads a data root.
- **The flag.** `roots.STATE_ROOT_AGREED` is True, and `bin/suite`'s default `TMP` branch is the suite root's `tmp/` (section 3.6). The two change together; `_launch.py` refuses a mismatch (`tmpdir_mismatch`). Only the engine's guard mode has the suite root as a write root: the test runner, `uisnap`, `release` and `vendor` never write under `~/betangel-data`, and their `TMPDIR` is the state root's `tmp/`. Tests use temporary HOMEs. The first engine command run with the real HOME creates `~/betangel-data/suite.noindex/` (0700) and its `tmp/`, after the run-marker check.
- **Why `~/betangel-data/suite.noindex`.**
  - It sits beside the data roots, so Nuance's discovery never sees it. That discovery is `archive_shas(root)` over `<root>/manifests` (market_index.py:927).
  - The `.noindex` suffix keeps Spotlight from indexing the suite's text derivatives (CSV exports, `session.json`, `report.json`, `commands.jsonl`). Yu is also asked to add all of `~/betangel-data` to Spotlight Privacy (Q-Y15), which Nuance called sensible (mailbox 08:57Z, B3).
  - Checkpoints and replay buffers live in memory only, which keeps on-disk derivatives to the catalogue, journals, ledger, reports and exports.

### 3.8 Configuration

`~/.local/state/betangel-suite/config.json`, with defaults in `betangel_suite/config.py`:

| Key | Default | Notes |
|---|---|---|
| `data_roots` | `[]` until the PRO index exists, then `["~/betangel-data/historic-pro"]` (the root Nuance named, Q-N4) | Each must pass `archive.check_data_root`. With no root, the engine runs synthetic mode only. The BASIC root is used only by explicit counts-only commands (section 5.1). |
| `state_root` | `~/betangel-data/suite.noindex` | R-4 (Yu); Q-N3 (Nuance: agreed on three conditions in Nuance's PR #4 review, conditional again since Nuance's PR #2 review; section 3.7) |
| `port` | 8765 | loopback only. `ssh-session`'s forced command requires 8765, the viewer key's port (`viewer_port_mismatch`; section 8.6 item 2) |
| `frame_hz` | 10 | 5-20 |
| `cap_profile` | `v1-live-mirror` | or `practice` (section 7.2; R-7) |
| `commission_source` | `user_package_unverified` | R-3 |
| `research_months_ruling` | `null` | A ruling id. While it is null, research months are hidden and not written to the catalogue (section 5.3). It stays null until Yu answers Q-Y7; no ruling id is accepted before then (Nuance, PR #1 review). Only null loads until a reviewed PR adds the ruling id to `config.ACCEPTED_RULINGS` (empty now), after Yu rules on Q-Y7 with Nuance and Astra; a config edit alone is refused (`config_invalid_value`; Nuance's PR #2 review, item 12; 3f51ae7). |
| `run_marker` | `~/.local/state/lab-runs/ACTIVE` (Q-N3: agreed by Nuance in Nuance's PR #4 review; conditional again since Nuance's PR #2 review) | section 6.8 |
| `watch_grace_s` | 600 | pause-unless-watched grace (section 8.6); accepted 60-3600 |
| `max_session_s` | 14400 | maximum session time (4 h) for every engine (`serve`, `open`, `ssh-session`), measured from engine start; the session then ends with reason `max_session` (section 8.6); accepted 600-86400 |

- **Reading `config.json` and the install salt.** Both are opened with `O_NONBLOCK`, and `fstat` judges them before any read, so a FIFO in either place is refused at once (`config_insecure`, `salt_invalid`; Nuance's PR #2 review, item 22; 53239a3). The pin's own reads do the same (e4ddc18).
- **Paper config.** It is `deepcopy(config.DEFAULTS)` (config.py:27-72), with the active cap profile merged in, plus:
  - `orders.paper.commission_rate = 0.02` and `commission_source`;
  - `orders.customer_strategy_ref` set to the ref the journal intents use: `suite-click` for operator sessions and `suite-test` in synthetic test mode.
  
  So V11 (validate.py:171-173), the config hash and the journal all agree. The DEFAULTS value is `bar-manual` (config.py:57), and the journal fold takes the ref from the intent (journal.py:620, :752).
- **Validation.** It is checked once at startup by the repo's own `config.validate_config` (config.py:254), against `paths.StatePaths(home=<suite root>/repo-home, root_override=<suite root>/repo-home/state)`. That override is accepted only with FORBID_NETWORK set (paths.py:58-72). Nothing is created; `StatePaths` creates directories only in `ensure()`. Nuance's conditions (Q-N8): the suite root is agreed and exists first, else the validation refuses with `subprocess_refused`; and this `StatePaths` object feeds only `validate_config`, because its `kill_engaged()` would be a false all-clear.
- **Git calls during validation.** Validation spawns `git -C <dir> rev-parse --is-inside-work-tree` through `paths.require_outside_worktrees` (paths.py:149, :158; config.py:224-236). So it runs inside the audit hook's startup phase, which allows exactly that argv (section 10).
- **Recorded as a hash only.** The validated config is never written whole into `session.json`, `report.json`, a journal note or `commands.jsonl`; only its `canonical_sha256` is. The reason is that every upstream writer the suite reuses runs `secret.refuse_forbidden` (journal.py:289; receipts.py:183, :211). That raises `SecretLeak` for any key, at any depth, that normalises to `session`, `token`, `headers`, `authorization`, `cookie`, `appkey` and similar (secret.py:114-133), and `config.DEFAULTS` has a top-level `session` section (config.py:41).

### 3.9 Development workflow and the suite's AGENTS.md

- **Branches and PRs.** Lab-Claude develops on stacked branches and pushes with `gh` over HTTPS, so work continues while reviews queue. Review routing is proposed up front (Q-N12); who merges is Q-Y8 (section 2.2.1). The table in AGENTS.md is the binding copy:
  - Astra reviews `guard.py`, `rx.py`, `errors.py`, `release.py`, `runmarker.py`, `api/`, the launcher, the boundary tests, the scanner (`tools/hygiene_scan.py`, `tools/pre-commit`, `tools/pre-merge-commit`, `tools/commit-msg`, `tools/pre-push`) and pin bumps;
  - Astra also reviews `cli.py`, uisnap (`betangel_suite/uisnap.py`, `tools/uisnap/`) and the staged scripts (`tools/stage/`). This row is lab-Claude's proposal, from Phase 0c's review plan; Nuance did not ask for it. It only adds a reviewer. It stays open for Yu to rule on with Nuance (Q-N12, Q-Y8);
  - Nuance reviews the data and paper paths (`data/`, `paper/`, `replay/`), the synthetic generator (`synthetic.py`, `tests/fixtures/`), the tick export (`tools/export_ticks.py`, `ui/ticks.json`), and every pin bump that changes an allowlisted file;
  - Astra and Nuance review `engine.py` and the roots (`roots.py`) jointly;
  - Astra and Nuance also review `config.py`, `docs/data-handling.md` and `tests/__init__.py` jointly (the Q-N12 additions in Nuance's PR #2 review). This row only adds reviewers;
  - any file no other row names goes to Astra and Nuance jointly. Nuance's PR #2 review asks for "a fail-closed row for unnamed files" but names no reviewer, so this choice is lab-Claude's reading, not Nuance's words. Nuance's PR #1 review (item 9) sends "uncovered diffs" to Yu instead. Which of the two the fail-closed row follows was asked of Nuance on 2026-10-17, not answered;
  - UI-only PRs (`ui/` with no change to routes, the command enum or `ui/ticks.json`) need only Yu's acceptance. This is a proposal: the packet asked Yu with no recommendation, and it was asked of Yu again on 2026-10-17, not answered (section 2.2.1).
  - **Rule documents: no row yet; asked of Yu on 2026-10-17, not answered.** AGENTS.md, this document, `docs/data-handling.md`, `docs/proposals/` and `tools/stage/` have no governance row of their own, so the author judges its own widening. Nuance recommends a governance row (PR #1 review, item 9, amending Nuance's view on Q-N12): these files go to Nuance and Astra, accepted at a named SHA; a diff that no row covers goes to Yu; and a change of meaning follows rule 10 unless both reviewers say it does not widen. Nuance's PR #2 review adds that "changes to AGENTS.md's rules or routing also need Yu". Yu rules. Until then, in lab-Claude's reading of "sensible" (section 2.2.1, labelled there as lab-Claude's), a PR that touches a rule document waits for both Nuance and Astra to accept the same head SHA. Nuance's "uncovered diffs go to Yu" would apply only if the fail-closed row (above) followed it.
- **Merging.** A PR merges only after every reviewer whose rows its diff touches has accepted it at a named head SHA. Lab-Claude merges.
  - The merge rule is Nuance's condition for Q-N12 ("agree once amended"; PR #4 review, 2026-10-16), with the joint row for `engine.py` and the roots and the additions to Nuance's own row. Nuance's PR #2 review sends "Every touched reviewer accepts the same head SHA" to Yu as a Q-Y8 clarification; Yu's 2026-10-16 answer is in section 2.2.1.
  - Who merges is Yu's 2026-10-16 answer to Q-Y8, "Its all good :) Merge when sensible", read as section 2.2.1 records. That reading, labelled there as lab-Claude's and not Yu's words, also requires the tests to pass on 3.13 and 3.11 at the accepted SHA. Yu can override it.
- **Collab.** Edit tasks use `root_path=/Users/user/betangel-suite`.
- **Upstream changes.** Any betangel-research change goes to Nuance as a proposal (section 14).
- **Yu's feedback channel.** Yu's acceptance and feedback reach lab-Claude only in a lab-Claude session that Yu types into (on the lab, or one Yu opens from the Air).
  - An acceptance checklist file that Yu edits is a log of Yu's checks, not acceptance in itself (Nuance, PR #1 review).
  
  Relays from Nuance or the mailbox are context, not acceptance.
- **The suite's AGENTS.md (binding on every agent):**
  1. **Paper-only MVP.** No credentials, Betfair API, network or live code. Never a "temporary" live endpoint. Later live and Air code never lives in this repo.
     - **The two R-2 viewer files are not network code under this rule** (Q-Y19, section 2.2.1). Yu chose option D: the R-2 approval already covered the two Air files of section 8.6 item 2, `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`, so the network clause does not cover them. This covers these two files and nothing else. Asked by lab-Claude whether a rule 10 proposal was also wanted, Yu answered on 2026-10-16: "yes to formal proposal". That proposal, `docs/proposals/002-air-viewer-files.md`, records its review and Yu's decision (section 2.2.1, Q-N15).
       - The limits these files keep (section 8.6): they serve only the viewer tunnel. The snippet is the Air's `Host lab-suite` block, and it offers only the viewer key. The self-test logs in only to that Host, over LAN SSH by public key only, never a password, and uses `nc` only on the Air's own `127.0.0.1`. They hold no credentials and no Betfair API code. They run only on the Air, which takes them only from GitHub at the reviewed merge commit's SHA; on the lab only the test harness runs the self-test, with fake `ssh` and `nc`.
       - Rule 1 is otherwise unchanged: other Air-side code and all other network code stay barred as before. Admitting more, or widening these two files, is a scope widening under rule 10.
  2. **Imports.** Only `rx.py` imports betangel_research, and only from the allowlist.
  3. **Orders.** Every paper order on real data is an operator click (the OperatorClick rule, section 7.1). Scripted orders (`TestOrder`) exist only in synthetic mode, which refuses every real data root. There are no rule-generated orders.
  4. **Licensed data.** Licensed data and its derivatives stay under `~/betangel-data`. Nothing licensed goes in git.
  5. **Agent conduct.** A model context counts as an upload. Agents (lab-Claude, Nuance, Astra) never put real rows, runner names, prices, market ids or per-market results into their context, Collab, the mailbox, PRs or issues.
     - Diagnostics print codes, counts, salted hashes and timings only.
     - Agents never read, search or list anything under `~/betangel-data` (the ledger `ledger/viewed-markets.jsonl`, `sessions/` and `private/` included), or the install salt (section 9.2, item 9). They use `bin/suite ledger-summary` and `bin/suite diagnose`. For lab-Claude's file tools, deny rules that Yu approved on 2026-10-16 back this up (Q-Y9). For Bash, Nuance's SSH shell and Astra it is conduct only.
     - Debugging uses synthetic fixtures. Screenshots are of synthetic markets only (uisnap).
     - No agent captures the screen, on either machine, while a suite page or an `ssh lab-suite` window is open (section 8.6).
     - **Exceptions: not available pending Q-Y9.** Real fields would reach a model context only with Betfair's written agreement naming the model provider, plus Yu's explicit OK each time, in Yu's own words, scoped to one problem report and named fields (section 8.7).
  6. **Commands agents never run.** Agents never run `open`, `ssh-session` or `--print-url`, and never send `attach`, `attach_viewer`, `new_code` or `viewer_code` to the real control socket, `~/.local/state/betangel-suite/run/control.sock` (section 9.1); tests send them only to engines in temporary HOMEs. They never POST to `/api/v1/command` or `/api/v1/bootstrap` on an engine with real data roots. `serve` and `open` never print a bootstrap code; only `--print-url` and `ssh-session`, used by Yu, do (`ssh-session` to its own SSH stdout). `stop` is allowed, because it only reduces activity.
     - `bin/suite test` exercises `open`, `--print-url` and `ssh-session` only in temporary HOMEs: with injected openers and piped stdin and stdout, or to see them refused before any engine starts. Nothing runs `/usr/bin/open`, and no test prints a code or a token outside its own pipes. Agents never run these commands otherwise.
  7. **Nuance's runs.** While the run marker exists, no suite engine or real-data command runs and nothing writes under `~/betangel-data` (section 6.8). Only Nuance's run wrapper creates or removes `~/.local/state/lab-runs/ACTIVE` and its `lab-runs/LOCK`; tests use temporary HOMEs; a stale marker is reported with codes and cleared only by the wrapper, or by Yu in Yu's own words (Nuance's PR #2 review, item 13).
  8. **No credential fields.** The suite UI never has credential fields. Any login prompt inside it is an attack.
  9. **Live-key data.** Paper or practice never runs on live-key data (section 2.3).
  10. **Scope.** Every widening of scope goes through the proposal process (section 14). Who judges whether a change widens is part of the governance row, asked of Yu on 2026-10-17, not answered (above).

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

The **upstream closure** loads no `socket`, `ssl`, `http` or `urllib`. The suite's own server does load `socket` and `http`, which is why the audit hook polices them (section 10). `subprocess` is loaded through `receipts` and `paths`, which is why the hook polices it too. `guard.arm()` imports `subprocess` itself, first. So `subprocess` keeps the original `_posixsubprocess.fork_exec`, behind its own `subprocess.Popen` event, while the module attribute gets the guard's refusing wrapper (I-5; 56a2631).

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
| `archive.ingest_archive(tar_path, data_root)`; `market_index.index_archive(root, sha)` | archive.py:765; market_index.py:870 | End-to-end data tests: a synthetic TAR is ingested and indexed into a temp root. Suite code never names them (`tests/test_ast_boundary.py`, I-10). |

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

**The contract test.** Nuance agreed it, narrowed (Q-N1, PR #4 review), after finding that seven injected breaks passed all tests. It is `tests/test_upstream_contract.py`, and **every pin bump is gated on it**: a bump merges only if it passes at the new pin (section 3.5 item 5). It reaches upstream only through `rx`.

- **Phase 0's names first.** `book.replay_market_time`, `receipts.parse_utc_ns` and the `ticks` names the suite uses (`LADDER_CLASSIC`, `to_hundredths`, `to_pence`, `is_on_ladder`, `tick_index`, `snap`): their signatures, and their behaviour on small synthetic inputs. The ladder is compared with Betfair's CLASSIC increments, typed in the test.
- **The other names Phase 0 code calls.** `MarketBookCache`, `strict_json_loads`, `secret.register`, `check_data_root`, `guard_path` and `PathDenied`: their signatures, and the result shapes the suite reads. For `MarketBookCache` that is the snapshot the engine reads after synthetic messages: its `status`, `inplay`, `version`, `invalid_reason` and `runners` keys, each runner's `status`, `ltp`, `total_matched`, `back` and `lay`, and `total_matched` None after an image with no `tv`.
- **Coverage.** The test fails when suite code uses an upstream name it does not list, so each new upstream name brings its contract with it. It counts `rx.<namespace>.<name>` however `rx` is reached (a name an import binds to it, or any `.rx` attribute, such as `engine.rx`), and also `<alias>.<name>` where `alias` is bound to a namespace by `from .rx import <namespace>` (with or without `as`, or `*`) or by `alias = rx.<namespace>`. The I-10 rule refuses those last spellings, so `rx.<namespace>.<name>` is the only spelling of an upstream name that the rule lets through; the test counts the others anyway (lab-Claude's round-3 review of #4 found it saw only the first). Neither reads a name built at run time (the I-10 row says what the rule does not refuse).

As later phases use them, it grows to fail loudly on a pin bump if any of these drift:

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
| Free PRO year, horse racing 2015-05..2016-04 (EX_ALL_OFFERS, TRD, TV, LTP, MARKET_DEF, SP_TRADED, SP_PROJECTED; sold as "tick-by-tick", but the files as observed record changes only, and changes may be conflated) | Downloaded by Yu to `incoming/data.tar`. Nuance ingests it into `~/betangel-data/historic-pro` (Q-N4). | **The only replay source.** Ladder replay and paper. The engineering year is already "seen", so using it spends no research months. |
| BASIC TAR (GB/IE WIN, 2015-05..2016-04 + 2023-01..2025-12, 1-minute LTP and definitions) | `~/betangel-data/historic` (ingested and indexed) | No UI mode. It is used only for counts-only checks run from the command line, in case the PRO ingest slips: a catalogue build and a reader smoke. Research months stay hidden. |
| Synthetic fixtures | Generated at test time into temp dirs by `tests/fixtures/gen.py` | All automated tests and every screenshot. |

Not on the lab, and never to be put there: the 2017 PRO samples (unless Yu fetches them), and any 2026 month, including the Air's delayed-stream recordings. Each 2026 month is refused by lab rule 4 and by `month_gate`.

### 5.2 Data roots and discovery

- The suite reads a configured list of indexed data roots. Each must pass `archive.check_data_root` (archive.py:273). It never reads `incoming/`. No data root is read while the suite root is not agreed (`roots.STATE_ROOT_AGREED` is False; Nuance, PR #1 review).
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
  - **Use a Safari Private window** on both machines, or a dedicated profile with no Betfair login, no extensions and no iCloud sync. In a normal window, Safari History, iCloud History and iCloud Tabs would sync the URL and title. Safari may also keep page thumbnails (*inference*).
  - `document.title` is static. The bootstrap code is single-use, so a copy left in history is already dead.
- **OS-level copies.**
  - The suite root's `.noindex` suffix keeps Spotlight out of it. Yu is asked to add `~/betangel-data` to Spotlight Privacy (Q-Y15).
  - Mac Analytics auto-submit is on, so a native crash report from python3.13 or Safari WebContent would be sent to Apple. That is put to Yu as a privacy decision (Q-Y14).
  - Data is kept out of exception text (section 9.2, item 9).
- **No upload, sync or share features.** Exports are 0600 CSV files under `exports/`, headed "Personal use only; Betfair Historical Data licence".
- **Viewed-markets ledger.**
  - `ledger/viewed-markets.jsonl` records, for every market opened: market id, plan, archive sha, month, role, wall time, furthest replayed pt, whether CLOSED was reached, the attempt count, the session ids, and any research-month ruling id.
  - **Agents never read it.** `bin/suite ledger-summary` prints counts only, by month, role, plan and attempt.
  - Nuance's trial ledger holds no market ids (trial_ledger.py:96), so there is no hash matching. Reconciliation is at month level, by the counts `ledger-summary` prints (Nuance's answer to Q-N11).
  - Nuance's answer to Q-N11 sets the fields at month level: a keyed hash, plan, month, role, opened_by, furthest phase, attempts and ruling id. The list above is brought in line with it when the ledger is built in 1a.
- **Agents never see rows** (section 3.9). `bin/suite selfcheck`, `catalogue`, `diagnose` and `ledger-summary` print codes, counts, salted hashes and timings only.

### 5.6 What never goes in git

- **File types:** `*.bz2`, `*.tar`, `*.sqlite*`, `*.jsonl`, exports, runs, screenshots outside `docs/synthetic/`, and any file over 512 KB. Enforced by `.gitignore`, `tools/hygiene_scan.py` and four git hooks: `tools/pre-commit` and `tools/pre-merge-commit` (the staged tree), `tools/commit-msg` (the message) and `tools/pre-push` (every commit and annotated tag a push publishes, messages included). The scanner also catches binary data anywhere in a file, data hidden in text (`encoded_blob`), and paths a clean filter rewrites (`filter_attribute`) (Nuance's PR #2 review, items 5, 19, 20 and 21; 50fe1b7, ebd1038, 6149d94, 526efcb, 268d02d). Lab-Claude's round-4 review and its recheck added:
  - every git call of the scanner has replace refs and grafts off (`GIT_NO_REPLACE_OBJECTS=1`, `GIT_GRAFT_FILE=/dev/null`), so it reads the blobs and parents a commit records and a push sends, never a stand-in (783125d);
  - `--push` refuses more than 1 MiB of pre-push lines (`push_input`) instead of cutting them short, which dropped every later ref (b4c2656);
  - **encodings decoded** (`encoded_blob`; 7085b08): base64 (standard and URL-safe); hex bare, split by one or two spaces or colons, right after `\x` (a PostgreSQL bytea literal), as `0x` lists, and in xxd, `hexdump -C`, `od -An -tx1` and `od`'s default octal output; `\xNN` escapes; decimal byte lists (a sorted list, such as a price ladder, is not data); and GIT binary patches. Runs join across lines, also when each line starts with the same comment or list marker, and a decoded run of text is searched once more (base64 of base64);
  - **known gaps, not decoded:** base32, base85 and Ascii85 outside a GIT binary patch, uuencode, quoted-printable, UTF-7, JSON `\u` escapes, base64 split into pieces under 16 characters (groups of 8, or a list whose first piece is that short), and lists split by commas;
  - **lists of hashes** (2ae7640, 287264a, b656145, fab0b92, 7126190, bfd2f6a): a hex run of two or more lines, each one whole token of exactly 40 or 64 digits (a list of commit or file hashes, bare, quoted or after a marker), is not counted as binary data while the lists in its file or message hold at most 64 lines in all, each line counted once, and while it is not in a decoded run. It is still flagged if an archive or SQLite magic, an image or document signature (PNG, JPEG, GIF, WebP, ISO media, TIFF, PDF) or a zlib stream starts at any of its lines, or if it holds text another rule flags, read with each NUL as a line end and other bytes that are not UTF-8 replaced, and, if it holds a NUL, read again with the NULs removed (UTF-16 text; fab0b92). Past 64 lines in all, every list in that file or message is binary data again, as before 2ae7640, and so is every list in a decoded run read as text, whatever the count; such a list that holds a NUL or is not UTF-8 is flagged at any length, not only from 96 bytes (bfd2f6a). Either way, a magic, an image or document signature or a zlib stream still counts at the start of any of its lines (145fa22; the final recheck of bfd2f6a, which had tested such a list from its first byte only, so an ASCII PDF on its second line passed). b656145 counted each run alone, so runs of 64 lines split by a blank line passed however many there were; counting per file or message is lab-Claude's decision (7126190; the finishing review's recheck). 7126190 still gave each decoded run a count of its own, so base64 runs that each decoded to a list of 64 lines passed however many there were, and past the count lists of two to four lines, under 96 bytes, still passed when split by blank lines (bfd2f6a; the recheck of 7126190). So the exemption carries at most 64 lines, about 2 KiB, in one file or message. A line with one hash and words after it is not a list and is not counted. Before 287264a and b656145 only the run's first byte was tested and only valid UTF-8 was read as text, so data after one real hash line, text with one NUL or 0xFF byte, and images and PDFs passed (round-4 finishing review). This also clears a false positive older than 7085b08: a bare list of three or more sha256 lines was flagged as binary from `encoded_blob`'s first version (6149d94) on;
  - **short runs** (53904f8): any other decoded run of 16 to 95 bytes that holds a NUL or bytes that are not UTF-8, too short to count as binary data, is read as text in the same way. Before 53904f8 it got neither test, so one record ending in a NUL, or after a 0xFF byte, passed (the finishing review's recheck; as old as 6149d94);
  - **known gaps, not flagged:** in lists of hashes, binary data with no signature above and no zlib stream at a line's start (raw deflate, a compressed file without its header, encrypted bytes, or a signature that starts mid-line), up to 64 lines, about 2 KiB, in one file or message, outside a decoded run (2ae7640, b656145, 7126190, bfd2f6a); and binary data with no signature in runs of under 96 bytes each, however many: a blank or other line every few lines, a change of marker, or text before or after the token on each line (a numbered list, trailing words), so that each run is too short for the binary test. One hash line alone between blank lines is such a run. This gap has no bound, and it is older than 2ae7640 (the recheck of 7126190 named it in general);
  - **known false positives** (failing closed): lists of md5, sha224, sha384, sha512 or blake2b sums, lists of lines that hold two or more hashes split by spaces (`git log --format='%H %P'`), lists of hashes that hold more than 64 lines in all in one file or message, however they are split into lists of two or more lines (7126190; at any length since bfd2f6a), and a list of two or more hashes in a decoded run, such as base64 of a text that lists commits (bfd2f6a). A word after each hash on its line avoids them;
  - **linear time** (805356c, 1be5dc1): no pattern grew worse than linear in an audit of 660 line shapes, once possessive quantifiers and an atomic group removed the backtracking found. `_SECRET_LOOSE` took 212 s on one 120 KB snake_case line, and six more patterns were quadratic or cubic. The audit missed string literals, which were tried again from every quote: a line holding `\x` and an unclosed literal full of escaped quotes took 16 minutes for 512 KB (round-4 finishing review). They are now read in one pass (1be5dc1). The regression test scans 20 lines of 200 KB, each within 10 s. The fix uses possessive quantifiers and an atomic group, so the scanner needs Python 3.11 or later: the hooks run it with 3.13, and the tests run on 3.11 and 3.13. `known_token` now reads a JWT with its own pattern, so a JWT that overlaps another provider token is found as well;
  - `runner_table` reads box-drawing tables (SQLite's `.mode box`, DuckDB), HTML cells, LaTeX's `&` and a fullwidth bar, accented names, and names in capitals when the row holds only prices (00067cd); `secret_value` reads unquoted values after a colon, after " is ", and after a bare space for `ssoid`, session token, app key and api key (c5a5576).
- **Fixtures:**
  - synthetic only, generated at test time, never committed as binaries;
  - reserved ids: markets `1.999xxxxxx`, events `99xxxxxx`, selections `9xxxxxxx`;
  - venue "Synthetic Park" and runners "Synthetic 1..n".
  
  The scanner fails on any `1.1[0-9]{8}`-shaped market id, or any runner-name table, outside that namespace. In synthetic mode the engine refuses non-synthetic ids and every configured real data root.
- **Scanner names.** The scanner compares its protected names (data-root components, forbidden directories, betangel-research copies, `betangel-data` in a link target or text) case-insensitively, with `casefold()`, because the lab's APFS volume folds case. Findings for runner data (`runner_table`, `runner_record`, `stream_record`), like the file-level data codes, withhold the file name.
- **Writing:** no real-market screenshots, prices, names or ids in PRs, issues, Collab or the mailbox. PR descriptions, review replies and other outbound text are scanned with `tools/hygiene_scan.py` before they are posted (Nuance, PR #1 review). No tool in this repo writes or posts such text (nothing under `tools/`, `bin/` or `betangel_suite/` calls `gh`), so there is no code path to wire the scan into: it is a manual step, written down in AGENTS.md, "Repository hygiene" (checked in round 4b).

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
  - "Void and rewind" (a typed confirmation) first applies STOP's order handling (section 7.6). It then closes the session as `voided_rewound`. The journal gets a `note`, the session is excluded from practice totals, and a new attempt starts with a new journal.
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
  - The basis is upstream's F60 (docs/betfair-facts.md): PRO historical data counts traded volume as backer's stake x 2, and Betfair says API `totalMatched` uses a different calculation.
  - F60 gives the x2 basis for the traded ladder (`trd`). **That the halving is right for the runner total (`tv`) is unverified**: upstream passes `tv` through raw (book.py:491), and synthetic `tv` always equals the sum of `trd`, so no synthetic test can catch a wrong basis (Nuance's PR #4 review, item 3). The UI label says so.
  - The divisor is a constant in `engine.py` (`TV_DIVISOR`), not paper's `traded_volume_divisor`, which is a fill-model parameter.
  - **Owed at the first PRO ingest:** a counts-only comparison of `tv` against the sum of the traded ladder.
- **Encoding.** One JSON object per frame, 5-20 KB (*estimate*), so 200 KB/s or less at 10 Hz. Delivered as NDJSON over a streaming `fetch()` (section 8.5).
- **Phase 0 (built).** The frame is a subset, built in `engine.py`. It carries `t` (`frame`) and `seq`, and every number in it is an integer:
  - clock: V, speed, paused and why, ms to the scheduled off;
  - market: id, name, status, in-play, version, `invalid_reason`;
  - every runner: id, name, status, LTP, traded volume (÷2 basis), and the best 3 back and lay with sizes.
  
  It has no effective speed, off-detected flag, bet delay, last-change age, WOM, book %, projected SP or ±40-tick subscribed ladders yet.

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
- **First PRO measurement.** At the first PRO ingest, count the markets and snapshots whose `non_finite_size` comes from SP fields (counts only), and feed the result into U-2.
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
  - It is checked first by `_launch.py`, before anything is created under `~/betangel-data`.
  - **Scope, by rule rather than by list** (Nuance, PR #1 review, item 5): every upstream step on real roots. That is real backtest runs, the PRO ingest and index, and the runbook's lab steps, its L2 and L3, certify-engine and reconcile-trials included. The runbook's section 10.1 runs bare commands today; Nuance adds a marker step to each of its blocks (Nuance's amendment to Q-N3). Upstream allows one tool per data root at a time (docs/backtest-plan.md:213).
- **At start.** The engine, every real-data command (`catalogue`, `selfcheck`, `diagnose`, `ledger-summary`), `uisnap`, `release` and `bin/suite test` refuse to start while the marker exists. An unreadable marker, or an unreadable marker directory, counts as present. `serve`, `open` and `ssh-session` check it again after taking `engine.lock`, so a marker written while they start refuses the start.
  - `ledger-summary` is lab-Claude's addition to Nuance's list: it reads only the suite root, but its output is a real-data derivative (section 8.6), and its `TMPDIR` lies under the suite root (section 3.6).
  - `bin/suite test` refuses in both tiers and on both interpreters (`test` and `test --py311`), with the same codes, `run_marker_present` and `run_marker_unreadable`. Tests were first exempt. Nuance answered Q-N14 "no": "Please make the fast tier refuse while the marker exists too; stop stays exempt" (mailbox, 2026-10-16 13:41Z; PR #4 review, item 14).
  - Only `stop` skips the check, because it only reduces activity (section 3.9, rule 6). `vendor` refuses too. It writes the deps clone under `~/.local/share` and, with `--bump`, `pin/`, and it clones the whole of `~/betangel-research`. It was first exempt by lab-Claude's own choice; Nuance's PR #1 review answered Q-N14 "test and vendor refuse under the marker; stop stays exempt".
  - A run already going checks the marker again after every test (`cli.marker_stop_result`). With worker interpreters (`-j`), the runner also checks it before it sends each module to a worker, and each worker before it starts a module. If the marker is present or cannot be checked, the run starts no further module or test and ends with the same code and exit 2. The tests then running are not stopped; they finish first, with anything they started. A worker that the marker meets in the middle of a module stops before that module's next test, tested since round 4b: `tests/test_launcher.py`, `ParallelRunnerTests.test_a_worker_stops_a_module_before_its_next_test_once_the_marker_appears` (0e2d289, fa1d529). The worker answers that it ran one test, not ok, with the marker present, and the module's second test never starts.
  - The engines that tests start run under temporary HOMEs, where no marker ever exists, so their own checks never see a real run. So the test helpers check the runner's real marker before each engine they start (`serve`, `open` and `ssh-session` children, uisnap's engine child, the in-process actor, and the commands `tests/test_release.py` starts from release copies) and before each inner `bin/suite test` run, and refuse with the same codes. A run announced mid-way then starts no further engine; the tests that would have started one fail (Nuance's PR #4 review, item 14: "check it before each engine launch").
  - An engine that a test has already started is not stopped: it runs until its test ends (an end-to-end UI test keeps one `serve` child for a whole client run). Nuance's wrapper waits on the real `run/engine.lock` and cannot see such an engine, because its lock is under the temporary HOME.
  - Nuance's PR #2 review answers Q-N14 the same way: "No. Drop `test` from NO_RUN_MARKER_CHECK; from #4 the fast tier starts ~20 temp-HOME engines blind to the real marker. Check it per module in _run_workers.assign()." `test` is not exempt, and the parallel test runner has that check (the bullet on worker interpreters, above).
- **The real-data lock** (Nuance, PR #1 review, item 5, and PR #2 review, item 6, which Nuance merges with it). The headless commands check the marker only at start and would hold nothing Nuance's wrapper waits on, so one started just before the marker would keep reading. So:
  - every real-data command (the engine and the four commands above) takes `LOCK_SH` on `~/.local/state/betangel-suite/run/realdata.lock` before it creates anything, `TMPDIR` included, re-checks the marker under the lock, and holds the lock for its life. In Nuance's words: "Every marker-checked command takes LOCK_SH before TMPDIR, re-checks the marker under it and holds it for life". Nuance wrote that at 93e26e6, when `test` and `vendor` were not yet marker-checked;
  - headless commands also check the marker between members, and the catalogue is built under a temporary name and renamed into place;
  - Nuance's wrapper takes `LOCK_EX` on it: "The wrapper waits 60 s+ for LOCK_EX, failing closed" (Nuance's PR #2 review, item 6). It is a separate lock, not `engine.lock`: in Nuance's words, "not engine.lock (stop would fail with control_failed)" (Nuance's probe);
  - I-17 has one test per marker-checked command (section 10);
  - **the lock's name: asked of Nuance on 2026-10-17, not answered.** Nuance's PR #1 review names it `run/realdata.lock` and Nuance's PR #2 review `run/active.lock`, for the same lock. This document and the code use `realdata.lock` until Nuance says which.
- **The real-data lock as built** (596d052, 18de53e, fbbc0c3):
  - **Who takes it.** Every real-data command (`cli.REALDATA_COMMANDS`: `serve`, `open`, `ssh-session`, `catalogue`, `selfcheck`, `diagnose`, `ledger-summary`) takes `LOCK_SH` on it without waiting (`run_lock_busy` while the wrapper holds it). It checks that the file is still the one at the path, checks the marker again under the lock, and only then creates its `TMPDIR`. It holds the lock until it exits. `cli.main` refuses `run_lock_not_held` for any other command whose `TMPDIR` would be made under `~/betangel-data`. `stop`, `vendor` and `release` make no `TMPDIR` (`cli.NO_TMPDIR`), so neither the check nor the lock applies to them (96d0bcc for `stop`; `release` is built on phase0/viewing).
  - **Why the marker is checked after the lock** (a lab probe): macOS `flock` grants a new `LOCK_SH` while a `LOCK_EX` waits. So a command that locks after the marker appeared refuses at once and lets go, and one that locked before is waited for.
  - **Who does not take it** (lab-Claude's decision; asked of Nuance on 2026-10-17, not answered): `test`, `uisnap` and `vendor`. None of them reads a data root or writes under `~/betangel-data`, each refuses under the marker at start, and holding the lock would let a long test run make the wrapper fail closed. The guard refuses their writes under `~/betangel-data` in their modes (`write_outside_roots`), but it does not judge reads: a read-only open under a temporary HOME's `betangel-data` succeeds in `test`, `uisnap` and `vendor` mode (a probe in round 4b's review). Code keeps their reads off data roots: tests use temporary HOMEs (section 3.9, rule 7), `uisnap` refuses any configured data root (`synthetic_only`), and `vendor` reads only `~/betangel-research` and its own roots. So a test that read a real data root would be neither refused nor holding the lock. A test shows that `test` and `uisnap` start while a stand-in wrapper holds `LOCK_EX`, neither taking the lock nor waiting for it (`tests/test_runmarker.py`, `RealDataLockTests.test_test_and_uisnap_neither_take_nor_wait_for_the_lock`; e9729a6). `stop` takes nothing and makes no `TMPDIR`: it must work during a run. On phase0/foundation `cli.main` refused it with `run_lock_not_held` until 96d0bcc, because its `TMPDIR` lies under `~/betangel-data`; phase0/http and phase0/viewing had the exemption already. `release` takes no lock either: it reads no data root and writes only its release copies, refuses under the marker at start, and checks the marker again before it renames a copy into place (section 8.6).
  - **Where it is.** In the state root's `run/`, beside `engine.lock`, which Nuance's wrapper already reaches. A lock under `suite.noindex` would need `suite.noindex` and its `run/` made before the locked re-check, which Nuance's item 6 rules out, and only the engine may write the suite root.
  - **The file.** The suite makes it once (0600) and never unlinks, renames or replaces it, and the guard refuses those calls (`run_lock_protected`): a holder of an old file and a wrapper locking a new one would not exclude each other. As the suite assumes the wrapper: it opens the file `O_RDONLY|O_NOFOLLOW|O_NONBLOCK`, counts a missing file as free, and never creates, truncates, renames or removes it. A lock file that is not a regular file owned by this user, with one link and no group or other write bit, makes every real-data command refuse (`run_lock_invalid`). So does a lock file that cannot be opened or locked, and a `run/` that cannot be made, as under a state root this user cannot write (c5fe696). Its directory `run/` is protected the same way: renaming or replacing `run/` would move the lock with it and split it as above, so the guard refuses a rename, replace or link at or from `run/`, even while `run/` is missing (lab-Claude's round-4 review; 6aeb1d5). `os.rmdir` stays allowed: it removes only an empty `run/`, which holds no lock. Those refusals hold `run/` and the lock where they are named, so in every mode `arm()` refuses a `run/` or lock that is a link, or that it cannot look at (`run_lock_invalid`), as `hold_shared` already did: through a link the lock would lie where no refusal reaches (the guard-paths review; b0d5c0d).
  - **Headless commands.** `catalogue`, `selfcheck --sample N` and `diagnose` call `runmarker.require_clear()` between members and stop at the first marker. The catalogue is written to a temporary name in its own directory and renamed into place (`os.replace`), so a stopped run leaves no partial catalogue. Owed when the catalogue is built; the writer helper will need a replace function, because `write_new` refuses existing names.
  - **Lab-runs.** The suite never creates or removes `lab-runs/ACTIVE` or `lab-runs/LOCK`, and the guard refuses any suite write in `lab-runs/` (`write_outside_roots`; tested in fbbc0c3).
- **Mid-session.** The actor checks the marker every tick, again after it dequeues each command (before running it), and before every journal append or ledger write. If the marker appears:
  - the engine pauses the clock and freezes `PaperExchange`: no advance, no activation, no journal or ledger writes;
  - the UI shows why;
  - the engine exits after a grace period of 30 s without writing.
  
  So the engine may hold `realdata.lock` (shared) and `engine.lock` for about 35 s after the marker appears, until it exits. Nuance's terms allow for that. For `engine.lock`: "Wait at least 60 s for engine.lock, and fail closed if it is still held" (Nuance's PR #4 review; Q-N3), and Nuance measured that lock free only after 30.23-30.60 s (PR #4 review, item 15). For `realdata.lock`: "The wrapper waits 60 s+ for LOCK_EX, failing closed" (Nuance's PR #2 review, item 6).
  
  An attached `ssh-session` holds `realdata.lock` too, but the engine it views is another process's, and it does not wait for that engine's end. Since round 4b (e9729a6; lab-Claude's decision, sent to Nuance on 2026-10-17) it checks the marker before every poll. Once the marker is present or cannot be checked, it writes `ended reason=run_marker` to its terminal, sends nothing to the engine (which sees the marker itself), and exits 2 with `run_marker_present` or `run_marker_unreadable`, as a hosting session ends; that lets the lock go. A poll already in a control request or a write finishes it first, so the worst case is one 5 s request or stalled write (`control.CONNECTION_TIMEOUT_S`, `WRITE_TIMEOUT_S`) plus `POLL_S` (0.25 s). In the I-17 test a stand-in wrapper waited 45.55 s for the lock before this change, and under 10 s after it, while the engine was still in its grace. So the 35 s bound stands.
  
  At the next start, after the run, the session is marked `interrupted_run`. It is not counted as abandoned by Yu.
- **Nuance's side (Nuance's terms, Q-N3).** Before touching sources or data, Nuance's wrapper:
  - creates the marker with O_EXCL, holding only the job kind, the UTC start and the pid;
  - waits for `~/.local/state/betangel-suite/run/engine.lock` to be free: "Wait at least 60 s for engine.lock, and fail closed if it is still held" (Nuance's PR #4 review; Nuance measured the lock free only after 30.23-30.60 s, item 15);
  - takes `LOCK_EX` on `~/.local/state/betangel-suite/run/realdata.lock`: "The wrapper waits 60 s+ for LOCK_EX, failing closed" (Nuance's PR #2 review, item 6). Every engine and real-data command holds that lock shared, so this also waits for them. In Nuance's PR #2 text the lock is `run/active.lock`; see the name, above.
  
  The waits are quoted from Nuance's reviews and not restated. Nuance's mailbox note of 2026-10-16 13:41Z worded the `engine.lock` wait differently: "wait up to 60 s for engine.lock, and refuse its own run if the lock is still held". Which wording Nuance wants was asked of Nuance on 2026-10-16, not answered.

  Nuance's PR #4 review adds:
  - a missing lock file counts as free, and any other error as busy;
  - the wrappers run outside betangel_research;
  - the wrapper removes only its own marker, and only after the job exits.
  
  Nuance's PR #4 review also had the wrapper hold a flock on the marker for the job's life. Nuance's PR #2 review moves it: "The flock moves from ACTIVE to a never-unlinked lab-runs/LOCK held for the whole job; judge staleness only while holding LOCK (a flock on ACTIVE removed a live marker in two probed races)."
- **The suite's own lock check** follows the same rule. `control.engine_running`, which `stop` and `uisnap` use, counts only a missing lock file as free; any other error counts as held. So `stop` fails with `control_failed` at its deadline, and never prints `not_running` or `stopped` while a lock it cannot check may be held (Nuance's PR #4 review: it "treats errors as free"); `uisnap` refuses with `engine_running`. A second engine was already kept out: `acquire_lock` lets an engine start only when it takes the lock, and raises on any error. `bin/suite test`'s state-root check reads the same lock the other way: `control.engine_lock_state` tells held, free and unknown apart, and only a lock that is definitely held explains `run/` entries (AGENTS.md, Phase 0 status F).
- **Owed on phase0/http and phase0/viewing** (lab-Claude's round-4 review). The lock is built and tested on phase0/foundation; the commands that serve and view are built on phase0/http and phase0/viewing, which owed what follows. Round 4b did each item on this branch, except the I-17 tests of `ledger-summary` and the headless commands, which come with their handlers:
  - `cli.main` keeps the `run_lock_not_held` check inside its `not in NO_TMPDIR` branch when phase0/foundation is merged into them. phase0/http has `NO_TMPDIR = ("stop", "vendor")`, as phase0/foundation now does, and phase0/viewing adds `release`; none of them makes a `TMPDIR` or takes the lock. phase0/http keeps the check there since its merge of 823c194, and phase0/viewing, with `NO_TMPDIR = ("stop", "vendor", "release")`, since its merge of phase0/http in round 4b.
  - An attached `ssh-session` (and `open`'s attach path) is a real-data command, so it holds `LOCK_SH` for its own life. On phase0/http `open`'s attach path holds it only while it sends one `attach`, hands the URL to `/usr/bin/open` and exits; it waits on nothing after that. On phase0/viewing `ssh-session` takes it in `cli.main` (`cli.REALDATA_COMMANDS`) since its merge of phase0/http in round 4b, and holds it until it exits, attached or hosting. Until round 4b an attached `ssh-session` noticed the engine's end only at its next heartbeat (`HEARTBEAT_S` = 15 s, after a heartbeat write that can wait `WRITE_TIMEOUT_S` = 5 s), so after the marker appeared its hold could reach about 50 s (30 s of grace, then up to 15 + 5 s), not 35 s, leaving about 10 s of the wrapper's 60. Lab-Claude's decision was to make it check the marker on every poll and exit, so that the 35 s bound stands and the stated bound is not raised (sent to Nuance for information on 2026-10-17). **Done in round 4b** (e9729a6): `Session.run_attached` checks the marker (`runmarker.state`) before every poll and leaves at once ("Mid-session", above). `open`'s attach path has no poll; since e9729a6 it checks the marker once more after the takeover's reply and before the hand-over, so a run announced meanwhile refuses (`run_marker_present` or `run_marker_unreadable`) and no URL goes to `/usr/bin/open` or stdout. The takeover itself has already happened by then: the engine has paused and every earlier code and token is dead.
  - The I-17 test for each real-data command (`serve`, `open`, `ssh-session`, `ledger-summary`, and each headless command as it is built) comes with its handler. On phase0/foundation the lock is tested through `catalogue` and `selfcheck` stand-ins. **On phase0/http `serve` and `open` have theirs since round 4b** (`tests/test_engine_process.py`, `RealDataLockTests`). Both take the lock in `cli.main` since phase0/http's merge of 823c194, and the engine runs in that same process, so it is held for the engine's life. The tests show that each command, `open` run through `cli.main` with a recorder in place of `/usr/bin/open`:
    - refuses with `run_lock_busy` while a stand-in wrapper holds `LOCK_EX`, and with `run_marker_present` when the marker appears between the launcher's check and the lock, in each case before its `TMPDIR`, `engine.lock` or any engine;
    - holds the lock shared while the engine it started runs, and lets it go when that engine stops;
    - lets it go after the marker appears within the grace period and its shutdown: with a 2 s grace, the stand-in wrapper got `LOCK_EX` after the grace and within 5 s more, which keeps the stated bound of about 35 s for the 30 s grace (tested for `serve`; `open` starts the same engine through the same `server.run`).

    **On phase0/viewing `ssh-session`, and `open`'s attach path, have theirs since round 4b** (e9729a6), all under temporary HOMEs:
    - `tests/test_session_process.py`, `RealDataLockTests`: an attached `bin/suite ssh-session` holds the lock, and lets a stand-in wrapper in within 10 s while the engine is still in its grace (45.55 s before e9729a6); a hosting session holds it and lets it go within a 2 s grace; while the wrapper holds `LOCK_EX`, `ssh-session` refuses `run_lock_busy` before any takeover, and the engine's tab keeps control; a marker made between the launcher's check and the lock refuses under the lock, before any `TMPDIR` or `engine.lock`;
    - `tests/test_engine_process.py`, `RealDataLockTests.test_open_attaching_holds_the_lock_and_hands_on_no_url_once_the_marker_appears`;
    - `tests/test_session_lifetime.py`: `run_attached` in process, with the marker present and unreadable.
    
    `ledger-summary` and the headless commands still owe theirs, with their handlers.
  - Tests there that rename `run/` inside a guarded child (in `tests/test_control.py` and `tests/test_guard.py`) must change, because the guard now refuses it (6aeb1d5). On phase0/http they changed in its merge of 823c194: the guarded child now asserts that renaming `run/` is refused (`run_lock_protected`), and `run/` is replaced by a link only by an unguarded interpreter that a test-mode child starts, as phase0/foundation's `BindTests` does. On phase0/viewing they changed the same way in its merge of phase0/http (round 4b).
- **No automatic work.** The catalogue is rebuilt only on an explicit command, never on a head change, so nothing fires during Nuance's ingest.
- **Until the marker half of Q-N3 is agreed again.** Lab-Claude runs no real-data commands while a run is announced, and Yu is told before starting. **The agreed marker is a Phase 0 exit criterion, and Phase 1b journal writes on real data do not ship without it.** Nuance's PR #2 item 6 is built on this branch (596d052, 18de53e, fbbc0c3); its re-check was asked of Nuance on 2026-10-17, not answered, and Nuance's agreement of the marker half is still owed. The decision on `test`, `uisnap` and `vendor` was also asked of Nuance on 2026-10-17, not answered.

---

## 7. Paper trading

### 7.1 Scope and the operator-click rule

- **What paper supports.**
  - LIMIT/LAPSE, one instruction per click, and whole-bet cancel.
  - Pre-off horse-racing WIN with one winner on a CLASSIC ladder (V9).
  - **The ladder-type condition** (Nuance, PR #1 review, item 1: a conditional P1 that fails closed). `book.py` takes the ladder type only from `priceLadderDefinition` (book.py:82-89, :459). Without the key, V9 refuses every click in paper mode with `ladder_not_classic` (validate.py:120-121), while the oracle has no ladder check (paper.py:232-251), so `PaperExchange` would have filled. Nuance found the key in none of the 2,121 definitions in the free 2017 samples (counts from the sample manifest). Whether the 2015-16 PRO year has it is *inference* until counted.
    1. **The count is Nuance's to run**, as the data owner, not lab-Claude's: BASIC engineering-year records with and without the key, in `checks.untracked_definition_fields` (counts only), and again at M-PRO.
    2. **If the key is absent:** Nuance's U-10 (section 14) with a fact row. Any CLASSIC default goes only at the book.py:459 call site, for historical ODDS markets. Any change to V9 goes to Yu under D-5.
    3. **Until the count is in,** section 0's "no policy amendment" and the Phase 1b exit (section 12) are conditional on it.
    4. **A keyless synthetic variant** (a definition with no `priceLadderDefinition`): built on phase0/http in round 4b, as the generator's `no_ladder_definition` option. It drops only that key; the market is otherwise byte for byte the same spec's without it. Tests show how the paths treat such a market today: upstream's book gives `price_ladder_type` None with an otherwise valid book; `validate_place` in paper mode refuses every click with exactly V9 `ladder_not_classic`, where the same market with the key gets no failure; and the engine's frame is the CLASSIC market's frame (section 11.1). V9 and any CLASSIC default are unchanged: they are Yu's under D-5, and U-10 is Nuance's. Nuance's count has since come in for BASIC: the key is in 0 of 12,208 indexed BASIC engineering-year markets (Nuance's mailbox note, 2026-10-17 08:41Z). In Nuance's words, "the condition holds, so it is a P1, no longer conditional", and the keyless variant "is now required, not optional". The M-PRO count is still owed: "Only BASIC is indexed; the PRO TAR is not ingested yet, so M-PRO's count is still owed" (Nuance). Items 1-3, sections 0, 1.2 and 12, U-10 and Appendix C item 1 still read the BASIC count as pending; that text comes from design/mvp-draft-0.2, where it is owed first, then merged up (Appendix E, round 4b's review).
  - GB/IE comes from the catalogue filter, not from a V-rule.
  - PRO members only.
- **The OperatorClick rule.** It enforces AGENTS.md:9 for this repo.
  - On an engine with real data roots, `PaperDesk.place`, `.cancel` and `.withdraw` take an `OperatorClick`. It is minted only by the per-request handler of `POST /api/v1/command`, carrying a fresh client nonce.
  - No timer, replay-loop or calculator code path can construct one. An AST test asserts that `OperatorClick(` appears only in `api/routes.py` handlers.
  - The green-up calculator only previews. Yu's Enter or click submits.
  - **What it proves.** I-8 is a code-path property: no suite code path creates an order without an HTTP request carrying a valid session token and a fresh nonce. It is **not** proof that a human clicked. Any holder of the token could POST (section 9.2). Like `presence.py`'s line (presence.py:1-11), it is friction and provenance, not identity. The agent-conduct rule covers the rest (section 3.9, rule 6).
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
  - any replace, drag or size reduction.
- **Practice loss limit.** It follows the active cap profile: £20 a day under `v1-live-mirror`, mirroring `max_daily_loss`, and £200 under `practice` (the table above). Whether it is useful is a question for Yu (Q-Y6). When the limit is reached, paper is disabled for the rest of the day, with an explanation.
  - It is never the journal fold's daily figure. The fold books each order's worst case, so in Nuance's probe a +£3.27 green-up counted as −£36.66 (PR #1 review).
  - Nuance asked for its day, figure and store to be defined. Proposed (lab-Claude's proposal, asked of Nuance on 2026-10-17, not answered; also for Yu's Q-Y6):
    - **the day** is the Europe/London calendar day of the wall clock, not the replayed race's date;
    - **the figure** is the sum over that day's sessions, voided ones included, of each session's official paper-v1 net where it has one, and otherwise the worst outcome of its matched position, net of 2% where positive;
    - **the store** is none of its own: the figure is recomputed from the day's `report.json` files under the suite root, plus the open session's position in memory.

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
   - V9: "suspended, in-play, not WIN or book invalid", with the sub-reason, for example `book_invalid` or `ladder_not_classic` (section 7.1);
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
- **Pending orders (SUBMITTING, before activation).** For 500 ms after a click, an order has no `bet_id` (paper.py:324-326). The upstream cancel interfaces work only by `bet_id` (paper.py:362; validate.py:322-327, :439-442), and the oracle has no cancel.
  - **The disposal.** So any cancel command that targets a pending order **withdraws** it. The actor removes it from the pending-activation list, and journals a `report {action:"place", paper_withdrawn:true}` moving SUBMITTING → REFUSED with a suite reason.
  - **Why it is legal.** SUBMITTING may move to REFUSED (lifecycle.py:41), and `transition()` sets `error_code` to the reason (lifecycle.py:150-151). A dry-run `transition()` checks the move first.
  - **The reasons:** `operator_stop_before_activation` for STOP and void-and-rewind; `operator_withdrawn_before_activation` for every other command.
  - **Parity.** The session is labelled "parity not checkable".
  - **Not chosen:** letting the order activate and then cancelling it at A, because it could take immediate fills the operator had tried to prevent.
  - **Nuance's answer to Q-N5 changes this for live-parity mode** (PR #1 review, 2026-10-16; Yu can override): "The 500 ms models an order in flight and step shows the activation book, so in live-parity Esc on a pending order activates then cancels; withdrawal only for void and badged exploration; readers use the folded error_code." Lab-Claude reads this as: in live-parity mode every cancel command, STOP included, lets a pending order activate at A and then cancels it, and withdrawal stays only for void-and-rewind and for exploration mode, which is badged. Whether "activates then cancels" covers STOP: asked of Nuance on 2026-10-17, not answered. The rest of this section, the keys in section 8.3 and the tests in section 11 are brought in line before 1b.
- **Keys and commands.** Each is one OperatorClick per command; pending orders are withdrawn and EXECUTABLE ones cancelled:
  - Esc: the last unmatched order, which may be pending.
  - Z: every back on the runner. X: every lay on the runner.
  - Shift+Esc: every order in the market.
  - Clicking our own order in the ladder: that order.
- **STOP** (button, Q, or `bin/suite stop`, which writes `run/STOP`; the engine polls it at 4 Hz):
  - freezes the clock;
  - withdraws every pending order (`operator_stop_before_activation`) and cancels every EXECUTABLE paper order by the cancel sequence above;
  - journals `halt {reason:"operator_stop", scope:"global"}`;
  - refuses new paper orders until the operator types `resume`.
  
  STOP does not end the session. `bin/suite stop` then also stops the engine, so the session ends as `stopped`; the button and Q do not (lab-Claude's proposal, section 7.10).
  
  `killswitch.engage` is never called on the lab. It would create the repo's global KILL file under the real state root.
  
  *As built in Phase 0:* `bin/suite stop` reaches the engine over the control socket (`stop`, section 9.1), and Phase 0 creates no `run/STOP` file (section 3.7).
- **Void and rewind** applies STOP's order handling, then closes the session (section 6.4).
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
    - the end status (below);
  - `report.json`.
  
  All writes go through `receipts.atomic_write_json`, `append_jsonl` or the journal, which run `refuse_forbidden` and `assert_clean`. Tests write a real `session.json`, a `report.json` and a note through these writers.
- **End statuses.** Nuance asked for `stopped`, `max_session`, `engine_failed` and `interrupted_crash`, and for "STOP's order handling before any end" (PR #1 review, item 11). When each status applies, and where STOP's order handling (section 7.6) does not run, is lab-Claude's proposal, asked of Nuance on 2026-10-17, not answered:
  - `completed`: the replay reached CLOSED, and the session was settled as the oracle does (section 7.6, at CLOSED). No STOP handling.
  - `not_closed_in_recording`: the member ended without CLOSED; pending orders are activated against the last yield, as in the oracle (section 7.6). No STOP handling.
  - `voided_rewound`: void and rewind (section 6.4).
  - `abandoned`: the watch grace period expired with nobody watching (section 8.6).
  - `max_session`: the maximum session time ran out (section 8.6).
  - `stopped`: the engine was stopped while the session was open, by `bin/suite stop` or by a stop signal (SIGTERM or SIGINT) to the process that hosts it. STOP from the button or Q does not end a session; it refuses new orders until `resume` (section 7.6).
  - `engine_failed`: the engine hit an error it cannot continue from, such as an unexpected exception in the actor, and ended the session itself before exiting.
  - `interrupted_run`: the run marker appeared (section 6.8). The engine exits without writing, and the status is written at the next start.
  - `interrupted_crash`: the engine exited without writing any end status (a crash, a kill or a power loss). The status is written at the next start.
  
  STOP's order handling runs before a `voided_rewound`, `abandoned`, `max_session`, `stopped` or `engine_failed` end, while the engine still holds the book. If the journal can no longer be written at an `engine_failed` end, the open orders are left for the next start.
  
  **At the next start** after `interrupted_run`, `interrupted_crash` or such an `engine_failed` (MVP: no crash resume), pending orders are withdrawn and EXECUTABLE ones cancelled from the journal fold, with no activation and no replay. There is no book at A then, and the marker freeze allows no activation (section 6.8). Under Nuance's answer to Q-N5, a pending order in live parity activates and is then cancelled (section 7.6), so this withdrawal would be a third case beside void and exploration. This withdrawal, and how STOP itself treats a pending order in live parity, were asked of Nuance on 2026-10-17, not answered.
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
     
     Left-click in the back column places a BACK at that price; in the lay column, a LAY. Clicking our own order cancels it, or withdraws it if it is pending. Drag-to-move exists only in exploration mode (R-7). The wheel scrolls; L re-centres on LTP; price orientation is a setting.
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
   - Caps panel: live v1 defaults and the active profile's usage (stake, orders per minute, daily paper loss), with flags for what live would refuse.
6. **Practice log** (Phase 1c). Daily and weekly totals: races, net, flat-at-off rate and refusals by rule. CSV export under `exports/` only.
7. **Settings and keymap (?)**
   - Stake presets: £2 (labelled "live v1 cap"), £5, £10, £20 and £50, within the active profile.
   - Start offset (default T-10 min), auto-slow and auto-pause, frame rate, sounds, orientation, contrast, and one-click versus confirm-each-order.
   - `PAPER_ASSUMPTIONS` verbatim.
8. **STOP (kill)** is always visible in the top bar and reachable by key and by CLI (section 7.6). It is labelled "STOP (paper)". The real kill switch arrives with live work on the Air.
   - *As built in Phase 0c:* a read-only tab cannot STOP. Its STOP button is disabled, Q and Shift+Q are ignored, and the server answers 409 `not_controller` (section 9.2 item 8). `bin/suite stop`, and claiming control first, still work. This conflicts with "reachable by key" above; open question Q-Y17, for Yu (Astra's view is at Q-A1).

### 8.3 Keyboard

Keys follow Bet Angel where that does not clash with replay control. They work only while the app tab has focus, and the browser's default action is suppressed.

| Area | Keys |
|---|---|
| Replay | Space play/pause; `+`/`-` speed; J then 1-6 jump (T-30/10/5/2/1/off); `[` `]` step 1 s while paused; `.` next pt batch; R random unseen race; N next race |
| Selection | Up/Down change runner; Tab cycle ladders; L centre on LTP; 1-5 stake preset |
| Paper | B back the focused runner at the best available-to-back price; A lay at the best available-to-lay price; Esc cancel (or withdraw, if pending) the last unmatched order; Z cancel or withdraw all backs, and X all lays, on the runner; C close trade (preview), then Enter to confirm; Shift+Esc cancel or withdraw all in the market; Q STOP |
| Help | ? keymap overlay |

There is no auto-keypress and no timed action, because those are automation.

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

- **How a release is made.** A release is a `git archive` of a merge commit on the merged main branch, named by its full SHA, installed after review by one command, `bin/suite release <merge-sha>` (guard mode release), run in the clean main checkout. Nuance's PR #1 review asked for this ("`release` takes the merge SHA"): a tag or branch name can be moved by any process of this user, and the full id is also the one the Air's two files are fetched at (item 2). It is built since cdda336; Phase 0c's first build took a tag.
  - It takes only a full lowercase object id, 40 or 64 hex digits: no name, abbreviation, `HEAD` or revision syntax (`release_commit_invalid`). `<id>^{commit}` must give the id itself, so the id of an annotated tag or of a tree is refused (`release_commit_unknown`), and local main must contain the commit (`release_not_on_main`; `release_main_missing` with no local main).
  - It refuses a dirty tree, tracked or untracked files (`release_dirty_tree`), git filter drivers in the repository's own config (`release_git_filter`), a gitlink in the index (`release_gitlink`: `git status` would enter that repository and run filters from its own config; it is checked first with `ls-files --stage -z`, and `status` never enters a submodule), an existing `app/<sha12>` (`release_exists`) and a left-over `app/.<sha12>.partial`. Nothing is fetched.
  - Its git runs with exactly `guard.RELEASE_GIT_ENV`: no user or system config, no prompt, and no replace refs or grafts (`GIT_NO_REPLACE_OBJECTS=1`, `GIT_GRAFT_FILE=/dev/null`; 972f555). Without them a `refs/replace/` entry in the checkout made `release <c1>` install another commit's tree under c1's id, and an `info/grafts` line let a commit main does not contain pass the main check. That is the class phase0/foundation fixed for `vendor` (section 3.5).
  - It git-archives that commit, never the checkout's `HEAD` or working tree, into `app/.<sha12>.partial`, and recomputes the git tree id from the copied bytes; it must equal the commit's tree.
  - It writes `RELEASE.json`: `{format: 2, commit, tree, files: {path: sha256}, executables}`, with no tag.
  - It makes the copy owner-only read-only (section 3.7), checks the run marker again, renames the copy to `app/<sha12>`, and switches `app/current` atomically through `app/.current.partial`.
  - **Every launch from a copy**, every command included (`stop` too), checks `RELEASE.json`: the copy is `app/<sha12>` of the commit it names, and the sha256s, the executable bits, no write bit, the owner, no extra entries, and the recomputed tree id match. Any mismatch refuses with a `release_*` code (`wrong_owner` for the owner check).
  - A release copy cannot make releases itself (`release_not_a_checkout`). Making the first release, after review, is Yu's decision (AGENTS.md, Phase 0 status D). Whether agents may ever run `release` is open (Q-Y18).
  - As built, `release` checks that main contains the commit (ancestry), as it did for tags. It does not check that the commit is on main's first-parent line, that is, one main itself pointed at. Whether it should is lab-Claude's open question from round 4b, not yet put to Nuance or Astra.
- **What a working checkout can do.** An engine whose code is not a release copy with a matching `RELEASE.json` runs in **synthetic mode** only: `serve`, `open` and `ssh-session` refuse every non-synthetic data root there.
  - *In Phase 0* every engine refuses every data root, a release copy's included (`synthetic_only`), and no release copy exists until Yu makes the first one. So Yu looks at synthetic markets from a working checkout.
- **Headless counts-only commands** (`selfcheck`, `catalogue`, `diagnose`, `ledger-summary`) read real roots only from a release copy, or from a clean checkout of a commit that main contains, because their output goes into an agent's context (Nuance, PR #1 review, item 4).
  - A filter on `sys.stdout` would not be enough: it misses `os.write(1, ...)` and child processes, and a grammar of bare integers passes ids and prices.
  - The alternative is a reviewed filter at the file-descriptor level (stdout and stderr `dup2`'d to pipes) that passes only codes and registered `key=value` pairs, and replaces anything else with `unlisted_output`.
  - Either way, tests plant leaks. On the reviewed-code route, a headless command with a planted leak, run from a dirty checkout or from a commit main does not contain, is refused before any real root is read. On the filter route, planted leaks never reach stdout or stderr.
- **Why.** Yu's viewing of licensed data never runs unreviewed code. `session.json` records the release tree hash.
- **Iteration.** In Phase 1a, Yu can look at work in progress in synthetic mode.

1. **The lab's own screen** (no change needed; available from Phase 0).
   - Yu runs `suite open --print-url` and pastes the printed URL, `http://127.0.0.1:8765/#c=<bootstrap code>`, into a Safari Private window within 120 s.
   - Plain `suite open` hands the URL to `/usr/bin/open` instead, before its guard seals. That opens the default browser in a normal window, and the URL is never printed.
   - With no engine running, `open` starts one and stays in the foreground, because it hosts the engine. It prints `opened port=<n>`.
   - If an engine is already running, `open` takes it over through the control socket: the engine pauses, and every earlier code and token dies. `open` gets a fresh code, hands it on the same way, prints `attached port=<n>` and exits.
     - It holds `run/realdata.lock` shared until it exits (section 6.8), and checks the run marker once more after the takeover's reply and before the hand-over (e9729a6). If a run has been announced meanwhile, it refuses (`run_marker_present` or `run_marker_unreadable`, exit 2) and no URL goes to `/usr/bin/open` or stdout; the takeover has already happened.
   - `serve` refuses `--print-url`, and `open` and `--print-url` are refused over SSH (section 3.6). `serve` and `open` print `ended reason=abandoned` or `ended reason=max_session` for those two ends only.
   - **While an engine is still starting** (it holds `run/engine.lock` but does not answer on `control.sock` yet), neither `serve` nor `open` waits for it, and neither asks again; only `stop` asks again until its deadline (section 6.8). Astra's re-review of #4 judged "Open/ssh-session not waiting during startup" "acceptable as a safe usability limitation", with "no requirement to give them stop's retry behavior"; of `serve` it says only that it "yields `engine_running`". `ssh-session` is built on phase0/viewing.
     - `serve` refuses with `engine_running` at once.
     - `open` sends one `attach` request. With no `control.sock` yet, or one that refuses the connection, it refuses with `control_unavailable` at once. The engine binds `control.sock` a moment before it starts answering on it: a request that connects in that moment waits for its reply, up to 5 s (`control.CONNECTION_TIMEOUT_S`), and attaches if the engine answers in time, else refuses with `control_unavailable`. Any other socket error also gives `control_unavailable`, and a reply it cannot read gives `control_failed`.
     - The same holds for an engine that is stopping, from when it removes `control.sock` until it lets `engine.lock` go.
     - Before either check, both take `run/realdata.lock` shared and check the run marker again under it (section 6.8), so while Nuance's wrapper holds that lock they refuse with `run_lock_busy` instead.
     - Tested in `tests/test_engine_process.py` (`LifecycleTests`), with `open` run through `cli.main` and a recorder in place of `/usr/bin/open`.
   - The page POSTs the code to `/api/v1/bootstrap`, gets a session token, keeps it in JS memory only, and strips the fragment with `history.replaceState`.
   - On the lab screen alone a second tab is never read-only, because both forms of `open` take the session over. No lab command mints a second code without a takeover (the control socket's `new_code` has no CLI caller). A read-only tab (section 9.2 item 8) needs a code from Enter in an `ssh lab-suite` window, so `claim_control` can be checked only after the viewer install (item 2).
   - Yu should sign out of historicdata.betfair.com in the lab's Safari, and delete saved betfair.com passwords and betfair.com site data there, now rather than after the downloads. The lab should hold no Betfair session (mailbox 08:57Z, B4, which asks for both; Nuance, PR #1 review). Asked of Yu on 2026-10-17, not answered (Q-Y11).
2. **From the Air: recommended, needs Yu's approval (R-2).** A forced-command, tunnel-only SSH key, plus an sshd drop-in.
   - **Staging.** Lab-Claude stages these files under `tools/stage/` and never runs them; tests run them only in a harness with fake `sudo`, `sshd`, `ssh` and `nc` (tests/test_stage.py). The `README.md` there takes Yu through every step.
     - `suite-viewer-setup.sh` (lab): `sh suite-viewer-setup.sh [--dry-run] KEY.pub` installs, and `sh suite-viewer-setup.sh [--dry-run] --undo` removes. It writes the drop-in first, and appends the `authorized_keys` line only after `sshd -t` and an `sshd -T` check of the effective values pass. It checks the drop-in against its fixed text before and after installing it, refuses an existing `200-lab.conf` with other content (`dropin_differs`), and puts both files back on any failure.
     - `air-ssh-config.snippet` (Air): exactly the Host block below.
     - `air-viewer-selftest.sh` (Air): the self-test below.
     - `suite-alias.zsh` (lab): the `suite` alias for Yu's `~/.zshrc`.
     - The Air takes its two files only from GitHub, at the reviewed merge commit's SHA (not a branch or tag name, which the lab's own `gh` login could move), never by AirDrop from the lab's copy. Any lab process running as `user` can change the release copy, and a changed snippet could run commands on the Air through `ProxyCommand`, `LocalCommand` or `Match exec`; the self-test from the same copy would not catch it.
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
       PreferredAuthentications publickey
       PasswordAuthentication no
       KbdInteractiveAuthentication no
       AddKeysToAgent no
       UseKeychain no
       LocalForward 127.0.0.1:8765 127.0.0.1:8765
       ExitOnForwardFailure yes
       RequestTTY no
       ServerAliveInterval 30
       StrictHostKeyChecking yes
       ControlMaster no
       ControlPath none
       ControlPersist no
       IdentityAgent none
       ProxyCommand none
       ProxyJump none
       PermitLocalCommand no
     ```
     - `PreferredAuthentications publickey`, `PasswordAuthentication no` and `KbdInteractiveAuthentication no` mean `ssh lab-suite` never falls back to a password prompt. The lab's sshd config leaves password logins on (OpenSSH's default) for other uses, so without these lines a refused viewer key (not installed yet, removed, or three wrong passphrases) would end at a `Password:` prompt, and the lab password typed there would open a full shell with no forced command. With them, ssh never asks for a password: a refused key ends at `Permission denied (...)`, where the list in brackets is what the lab's sshd offers, so it still names `password`. The self-test's own logins also pass the three as `-o` options, which no config block, `Match` included, can override.
     - The passphrase, together with `AddKeysToAgent no`, `UseKeychain no` and `IdentityAgent none`, means no other process on the Air can use the key silently. That includes Nuance, which runs as the same user.
     - `ControlMaster no`, `ControlPath none` and `ControlPersist no` mean an open `ssh lab-suite` leaves no shared connection that another Air process could reuse without the passphrase.
     - `ProxyCommand none`, `ProxyJump none` and `PermitLocalCommand no` stop a later `Host *` block from adding a proxy or a local command. ssh keeps the first value it reads, so the block goes at the top of `~/.ssh/config`, above any `Host *` or `Match` block. The self-test refuses to start unless `ssh -G` shows the seven hardening lines (`ControlMaster`, `ControlPath`, `ControlPersist`, `IdentityAgent`, `ProxyCommand`, `ProxyJump`, `PermitLocalCommand`) and the three authentication lines in force, for `ssh lab-suite` and for each of its own logins.
   - **Use.** Yu types `ssh lab-suite` on the Air. Do **not** use `-N`: a forced command runs only when a session channel is opened.
     - `bin/suite` checks `SSH_CONNECTION` and `SSH_ORIGINAL_COMMAND` before `env -i` (section 3.6).
     - `ssh-session` without `--port`, which is how the forced command runs it, serves or attaches only on 8765, the port of `permitopen` and the `LocalForward`. Another config `port` refuses with `viewer_port_mismatch` before any engine starts, and so does a running engine on another port (from `serve --port N` or `open --port N`), before any takeover.
     - It prints a single-use URL (`http://127.0.0.1:8765/#c=<code>`; code valid for 120 s) to that session's stdout only.
     - Yu pastes the URL into a Safari Private window (Cmd-click would open a normal window).
     - Pressing Enter in the ssh window prints a fresh code, for example after a page reload.
   - **What the ssh window shows.** The session's stdout carries only these lines (`api/sshsession.py`):
     - the URL, at the start and again for every Enter;
     - `heartbeat h:mm:ss` every 15 s: the time since this viewer attached;
     - one `ended reason=<code>` when the viewer's part ends: `superseded`, `engine_gone`, or the engine's own end reason (`stopped`, `abandoned`, `max_session`, ...). It is `run_marker` when the run marker appears: a hosting session prints it when its engine ends after the grace, and an attached one at once, without waiting for the engine (section 6.8). `refused:run_marker_present` (or `_unreadable`) then follows on stderr.
     
     ssh shows the session's stderr in the same window. It carries only code-only lines, and these are not attacks:
     - `http:<status>:<code>` or `http:error:<class>` from the engine's HTTP server, when this `ssh-session` hosts the engine: for example `http:401:bad_code` after a page reload;
     - `refused:<code>` or `error:<class>` when `bin/suite` refuses or fails: for example `refused:run_marker_present` during a Nuance run.
     
     Anything else the session prints is an attack, for example text asking for a password, or a URL with another host or port (see the trust boundary below).
   - **Session lifetime: pause unless watched** (an MVP invariant, I-19; `api/lifetime.py`):
     - The actor auto-pauses when the controller tab's stream drops or the page reports `visibilitychange` hidden. While hidden, the page asks again on any stream message that shows the clock running (a Play accepted just before hiding, or a pause that failed), one request at a time, and stops asking after `not_controller`.
     - `ssh-session` writes the heartbeat line every 15 s and reports it to the engine. A failed write, a write that stdout does not take within 5 s (an SSH channel still open that nobody reads; a blocking write would hold the engine's loop, its lifetime checks and its stop), stdin EOF or SIGHUP means the viewer has left, and a viewer silent for 60 s counts as away. The engine then pauses and keeps the session for `watch_grace_s` (default 10 min) instead of stopping.
     - With no engine running, `ssh-session` hosts the engine in its own process. So that process, and `ssh lab-suite`, lasts until the engine ends, and then prints the end reason (unless it has already printed `ended reason=superseded`). An `ssh-session` attached to a running engine exits at once on stdin EOF, while the engine keeps the grace. It also exits at once when the run marker appears, before the engine's own end (section 6.8).
     - **Signals.** Under a hosting `ssh-session`, SIGHUP means the viewer left (the grace runs), and SIGTERM and SIGINT stop the engine. An attached `ssh-session` treats all three as the viewer leaving.
     - A new `ssh lab-suite` (or `suite open`) during the grace **takes over** through the control socket. The engine pauses, invalidates every earlier code and session token, and issues a fresh code. It is not refused. Journalling a note of the takeover is deferred to Phase 1b, because Phase 0 has no journal.
     - **Nobody watching** means the terminal viewer is away and no tab is streaming. Only when nobody has watched for the whole grace is the session marked `abandoned` and the engine stopped.
     - A takeover by `suite open` hands the session to the lab's screen, which has no terminal viewer. Such a session never ends as `abandoned`. It ends on `suite stop`; on a stop signal to the process that hosts the engine (SIGTERM or SIGINT, and SIGHUP too when `serve` or `open` hosts it, as when its Terminal window closes); at the maximum session time; when the run marker appears (reason `run_marker`, after the 30 s grace of section 6.8); or on an engine failure. In Phase 0 the page's STOP only pauses the engine. The same holds for an engine started by `serve` or `open`, until an `ssh-session` takes it over.
     - The maximum session time, `max_session_s` (default 4 h), applies to every engine (`serve`, `open`, `ssh-session`), measured from the engine's start. The session then ends as `max_session`.
     - **The bound for a silent disconnect** (the lid closed or Wi-Fi gone, with no clean close; Nuance, PR #1 review, item 8). Through `ssh -L`, the lab's sshd keeps reading the stream into a 2 MiB window, so the engine's writes do not fail. In Nuance's probes, a loopback sshd sent no keepalive while a 17 KB/s stream flowed and timed out after about 135 s; on a tip copy, a peer that reads and never closes kept the clock running for all 40 s of the probe. So today a silent disconnect pauses only within about 3 min (longer while paused; *inference*).
     - **Owed before Phase 1b, with a test:** the actor pauses with reason `not_watched` after about 5 s with no request from the playing controller.
   - **What the key can and cannot do.** Lab-Claude stages an Air-side self-test, `air-viewer-selftest.sh`, which Yu runs right after installing the key (Nuance may start it, but only Yu types the passphrase).
     - Before any login it runs `ssh -G`, which reads the config and connects nowhere, for six forms: the plain `ssh lab-suite`, and the exact arguments of each of its five logins (the same `-o` options, forwards, and command or session type). A `Match` block (`sessiontype`, `command`) can change one form and not another, and `IdentityFile` and the forwards add up across blocks wherever the lab-suite block sits (proposal 002, section 5.6).
     - It refuses to start unless every form shows the block's host, user, address family, `AddKeysToAgent`, `IdentitiesOnly`, `ExitOnForwardFailure` (`no` for the `-R` login, which passes it) and `StrictHostKeyChecking` values, the three authentication lines and all seven hardening lines. Each form must also show exactly one identity, the viewer key, and no forward but the Host's `LocalForward` and the probe's own (none for `-W`, where ssh drops the config's forwards). It does not check `UseKeychain`, `RequestTTY`, `ServerAliveInterval`, `ForwardAgent` or `ForwardX11`; the viewer line's `restrict` refuses agent and X11 forwarding on the lab.
     - It makes nine probes over five logins, and reports each one as refused or ALLOWED. A probe counts as refused only with evidence in the `ssh -v` log: the lab accepted the viewer key ("Server accepts key"), no "Will attempt key", "Offering public key" or "Server accepts key" line names another key, there is no "Trying private key" line, the login succeeded, and the lab refused. ssh always has the viewer key's public half (an ed25519 private key file keeps it unencrypted), so it offers that key, and "Trying private key" never appears for it.
     - The probes: a requested command (the launcher refuses it); a PTY; `-L` to another port, to another host, to `localhost:8765` (`permitopen` names `127.0.0.1` only) and to a Unix socket; `-W host:22`; `-R` to a TCP port (port 0) and to a Unix socket.
     - The verdict is PASS only if all nine were refused. On FAIL, Yu runs the undo on the lab at once.
   - The existing Air agent key keeps `no-port-forwarding` and is never used for Yu's UI. Removing the viewer line revokes access.
3. **Alternative: macOS Screen Sharing** on the lab, which Yu turns on in System Settings. It is broader: full desktop control from the LAN.
4. **Not recommended:**
   - binding the engine to the LAN (Bet Angel's port-9000 anti-pattern);
   - a VPN or exit node (lab rule 5);
   - copying licensed data to the Air;
   - running the MVP engine on the Air next to the Betfair credentials.

**The trust boundary.** The tunnel makes lab-served JavaScript run in Yu's Air browser. That JS is written by lab-Claude and is replaceable by any lab process running as `user`; `chmod a-w` does not stop the owner. This is the only lab-to-Air code path: the two Air files of item 2 reach the Air from GitHub at the reviewed merge commit, never from the lab. Rule 1's network clause does not cover them (section 3.9: Yu's ruling on Q-Y19, and proposal 002).

A buggy or tampered page could show a fake Betfair login and send what Yu types to the lab. The CSP cannot prevent that, because the lab sets it. Hence:

- the suite UI never has credential fields, so any login prompt in it is an attack;
- use a Private window, or a profile with no Betfair login, on both machines;
- suite components on the Air never listen on TCP loopback (Unix sockets only). Other Air services do: Nuance counted 10 or more TCP loopback listeners on 2026-10-16 (PR #1 review, item 7). Because the lab sets the CSP, a tampered page at `127.0.0.1:8765` can send blind requests and WebSocket handshakes to any Air loopback port, and they pass localhost Origin allowlists. None is exploitable now; one with its login stopped would be, which is Yu's to fix in that service's own repo. So the Air's TCP loopback listeners are checked (netstat) before R-2 viewing starts, and L1 closes this only with a tested deny-all content rule;
- the later native shell uses `WKWebsiteDataStore.nonPersistent()` and no `console.log` of data.

**The forced command is same-uid too.** Any lab process running as `user`, an agent included, can replace the forced command, the release copy it runs, the shell startup files sshd runs before it, and `~/.ssh/authorized_keys` itself. That file holds the viewer line's `from=`, `restrict`, `permitopen` and `command=` options, so such a process can also widen what the key may do. The copy's read-only modes stop accidents, not the owner.

- Only the root-owned drop-in is beyond such a process: no `-R`, no Unix-socket forwarding and no listeners. It keeps `AllowTcpForwarding local`, so with `permitopen` edited away, `-L` to any host and port would work again.
- The Air self-test confirms the key's limits only when it runs, at install time.
- Such a process could also print anything in the `ssh lab-suite` window and serve anything on the lab's `127.0.0.1:8765`. So Yu treats anything in the window beyond the lines listed under "What the ssh window shows" (item 2) as an attack, closes the window and runs the undo.

**What reaches the Air.** Replayed prices appear on the Air's screen and in the browser's memory. In a normal window, Safari History, iCloud History and iCloud Tabs would also sync the URL and `document.title`. Safari may also keep page thumbnails (*inference*). The Private window, the static title and the single-use code address this. It is still personal internal use, and the question is put to Yu anyway (Q-Y2).

**Screen capture on the Air** (Nuance, PR #1 review, item 6). R-2 puts real races, and a live bootstrap code, on the Air's screen.

- A Claude Code shell on the Air passes `CGPreflightScreenCaptureAccess()` (Nuance checked the preflight only and took no capture), so `screencapture` would get the whole display with no prompt. Computer use is a second path.
- Rule 5 forbids capture while a suite page or an `ssh lab-suite` window is open. That is conduct only, and sessions in other repos on the Air never read this repo's AGENTS.md.
- A line in the Air's CLAUDE.md saying the same: asked of Yu on 2026-10-17, not answered (Q-Y10). Q-Y10 covers the Air before its first real race.

### 8.7 Feedback and problem reports

- **Report a problem.** A `report_problem` command (a button, with an optional fixed category) writes `reports/<session_id>-<n>.json` under the suite root. It contains:
  - the session id and attempt;
  - the virtual pt as an offset from the scheduled off;
  - the last N command codes;
  - counters, `invalid_reason` codes and frame timings.
  
  It contains no names, prices or market ids.
- **Diagnose.** `bin/suite diagnose <report>` replays that session's member headless to the reported offset, reads the existing journal, and prints codes and timings only. It does not re-execute orders on real data (R-6).
- **Real values: not available pending Q-Y9** (Nuance, PR #1 review, item 2). When structure is not enough, Yu describes the shape, or lab-Claude adds a code-only check to `diagnose` that prints codes. Agents never read real values.
  - **Why Yu's OK alone is not enough.** It would put named real fields into a hosted model context, which counts as an upload (rule 5, section 3.9). The licence prohibits "the use of the Historical Betfair Data by, another organization or individual" unless "a specific agreement in writing with Betfair exists", and Betfair has not ruled on model providers (proposal 001, sections 5.1-5.2).
  - So real fields would need Betfair's written agreement naming the provider, plus Yu's OK in Yu's direct channel (section 3.9), scoped to one problem report and named fields. Yu's answer would be recorded in the report folder, and nothing beyond that scope read.
  - No "same-shape" fixture is ever derived from a real report: it would still be a licensed derivative (proposal 001, section 3.2).
- **Acceptance.** Yu works through each phase's checklist and gives acceptance in that channel, in Yu's own words. A checklist file that Yu edits is a log of Yu's checks, not acceptance (Nuance, PR #1 review; section 3.9). Relays from Nuance are context, not acceptance.

---

## 9. Local API and security

### 9.1 Transport and the closed route table

- **Bind.** A `ThreadingHTTPServer` subclass binds `127.0.0.1:<port>` only and asserts `getsockname()` after the bind. There is no IPv6 wildcard, no `SO_REUSEPORT`, and no fallback port: a failed bind aborts.
- **Overrides.**
  - `server_bind` skips `socket.getfqdn()` (`http.server.HTTPServer.server_bind` calls it), so no name lookup ever runs.
  - `log_message` logs codes only: no paths, query strings or tokens.
  - `handle_error` (which by default prints a full traceback, socketserver.py:372-383), `sys.excepthook` and `threading.excepthook` print only the exception class and a code. Full tracebacks go only to 0600 files under `private/`, which agents never read.
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
- **Control socket.** `run/control.sock` (0600, in the 0700 run dir) accepts only `attach`, `new_code`, `pause` and `stop`, plus `ssh-session`'s `attach_viewer` (`{port: <the port it expects, 0 for any>}`; an engine on another port answers `viewer_port_mismatch` before the takeover; the reply adds `viewer`, the viewer generation), `viewer_code`, `viewer_heartbeat` and `viewer_away` (each `{viewer: <positive int>}`).
  - A viewer that a later takeover has replaced gets `{ok: false, code: superseded}`.
  - Each request is one line of strict JSON with exact keys, from the same uid only (checked with the kernel's `LOCAL_PEERCRED`, which `getpeereid` is built on).
  - Clients connect only to a path permitted with `guard.permit_unix_connect` before `seal()` (I-3); an attached `ssh-session` keeps that permit after it seals.
  - In Phase 0, `new_code` has no CLI caller.
  - `new_code` and `viewer_code` mint a fresh bootstrap code for whichever same-uid process asks, silently: nothing is printed to Yu, opened or paused. Nuance's PR #1 review says "`new_code`/`viewer_code` mint silent tokens"; what "silent" covers here is lab-Claude's description. Agents never send `attach`, `attach_viewer`, `new_code` or `viewer_code` to the real control socket under `~/.local/state/betangel-suite/run/` (rule 6); tests send them only to engines in temporary HOMEs. That is conduct only (section 9.4).
    - Nuance's review asks for this text, not a code change, and the code is not changed (round 4b; `api/control.py` and `api/routes.py` say the same since 0a3cc26). `new_code` is the tests' own way to get codes, in eight test modules, and a same-uid process could take the session over through `attach` anyway (section 9.4). `viewer_code` names its viewer by a small generation number (1, 2, ...), so a same-uid process can guess it; an unguessable per-viewer token would close that path for other processes, but not `new_code`'s, so the residual in section 9.4 would not change. Lab-Claude has not built it; whether to is lab-Claude's open question, not yet put to Nuance or Astra.

### 9.2 Authentication and request checks

1. **Bootstrap code and session token.**
   - Each `open`, `ssh-session`, takeover or Enter press issues a **single-use bootstrap code** (`secrets.token_urlsafe(16)`, valid for 120 s, invalidated on first use).
   - The page exchanges the code by `POST /api/v1/bootstrap` for a **session token** (`secrets.token_urlsafe(32)`).
   - The server keeps the token in memory only, never on disk. The page keeps it in JS memory only, never in `sessionStorage` or `localStorage`. A reload needs a new code.
   - So the copies of the URL in `ps` (the `/usr/bin/open` argv), browser history, iCloud or Terminal saved state are already dead.
   - Both values go through `secret.register`, so any journal or receipt write that contains one is refused (`assert_clean`; journal.py:296; receipts.py:185, :214).
   - The token is required as `Authorization: Bearer` on every `/api/` request except `bootstrap`, the stream included, and compared with `hmac.compare_digest`. A missing or wrong token gets 401.
   - There are no cookies, because cookies on `127.0.0.1` are shared across ports, and no query-string tokens.
   - A takeover invalidates the previous token.
2. **Host.** The host name must be exactly `127.0.0.1` or `localhost`, with a numeric port; otherwise 421. This defeats DNS rebinding. The staged Host block fixes the Air's side at 8765 (`LocalForward 127.0.0.1:8765` with `ExitOnForwardFailure yes`), so if 8765 is taken on the Air, `ssh lab-suite` fails instead of using another port.
3. **Origin.** It is required on POST and must equal `"http://" + Host`; otherwise 403. If present on the stream GET, it must also match.
4. **POSTs.** POST only, with `Content-Type: application/json`; anything else gets 415. Simple cross-site form, text or `no-cors` POSTs therefore fail, and a JSON POST needs a preflight that is never answered.
5. **No CORS.** No `Access-Control-*` header on any response, and `OPTIONS` gets 405.
6. **Bodies.** Parsed with `receipts.strict_json_loads` (receipts.py:247: duplicate keys and NaN are refused), against exact-key schemas. The limit is 64 KB, with 413 above it, plus per-route rate limits.
7. **Idempotency.** Every command carries a client nonce. A replayed nonce returns the first result and does nothing new. Nonces are kept for the serve process's life, however many commands follow. A command answered `engine_busy` has not run and never will. `place` and `cancel` append with `expect_head` (section 7.3).
8. **One controller tab.** A second tab is read-only until it sends `claim_control`.
   - `claim_control` is the one command a read-only tab may send; everything else, STOP included, answers 409 `not_controller`.
   - The page learns its role from the `session` query (polled every 2 s) and from 409 replies. A read-only tab shows a READ-ONLY chip and a Take control button.
   - So a read-only tab cannot STOP, which conflicts with section 8.2 item 8. `bin/suite stop`, and claiming control first, still work. Open question Q-Y17, for Yu (Astra's view is at Q-A1).
9. **Errors are codes only.** No tracebacks, request bodies, data rows or identifiers. Upstream exceptions are mapped at the `rx.py` boundary:
   - The caught exceptions are `IndexProblem`, `ArchiveProblem`, `PathDenied`, `ValueError` and `JournalError`. These embed member paths, which contain real event and market ids: for example `where = f"raw:{member['path']}"` (market_index.py:726) and `_label(name)` (archive.py:298, :348, :815).
   - The boundary keeps only the reason after the last colon, from a closed enum. Any identifier is replaced with a salted hash. The salt is per install, in a 0600 file at `~/.local/state/betangel-suite/install-salt`, not under the suite root (AGENTS.md adaptation B): the first process that hashes makes it, and only the engine may write the suite root.
   - **The hashes are pseudonymous, not anonymous** (Nuance, PR #1 review, item 3, and PR #2 review, item 14, which estimates about 427k HMACs a second per core). The hashed labels follow the public member layout (archive.py:245-264), so a ref for an event file reverses by enumeration in about 13 minutes on one core. So the salt is on rule 5's never-read list, with its own Read deny (Q-Y9), and it is never regenerated.
   - **Moving it: proposed; asked of Nuance on 2026-10-17, not answered.** Nuance wrote "Move the salt, never regenerate it" (PR #1 review, item 3); whether that means the file or the doc text is part of the question. Lab-Claude's proposal, for Nuance to confirm: the engine moves the file byte-for-byte from `~/.local/state/betangel-suite/install-salt` to `~/betangel-data/suite.noindex/install-salt` at its first start after Nuance agrees, so the `~/betangel-data` deny covers it. It is never regenerated, and its own Read deny stays until the move has happened.
   
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
| **Lab-served JS running in Yu's Air browser** (the only lab-to-Air code path) | No credential fields (any login prompt is an attack); Private window or a profile without a Betfair login; no suite listeners on the Air; reviewed release copies only; the Air's staged files only from GitHub at the reviewed merge commit's SHA, never from the lab (section 8.6) | A tampered page can still show anything on screen; Yu's rule is never to type credentials into it. It can also send blind requests and WebSocket handshakes to other Air loopback services (section 8.6): a netstat check before R-2, and L1's tested deny-all content rule. |
| **Same-uid processes, including agents, holding or minting the token** (lab-Claude locally; Nuance through Nuance's full-shell key) | Single-use codes; token in memory only and registered with `secret`; `open` and `--print-url` refused over SSH; the agent-conduct rule (agents never run `open`, `ssh-session` or `--print-url`, never send `attach`, `attach_viewer`, `new_code` or `viewer_code` to the real control socket, and never POST commands on a real-data engine); the passphrase-protected viewer key | Not preventable against a determined same-uid process, as in the repo's own threat model (presence.py:1-11). I-8 and I-16 are code-path properties, not proof of a human. The viewer key's forced command, the release copy, the shell startup files and the viewer line in `authorized_keys` (its `from=`, `restrict`, `permitopen` and `command=` options) are same-uid replaceable too. Only the root-owned drop-in's limits (no `-R`, no Unix-socket forwarding, no listeners) are beyond such a process, and the Air self-test confirms the key only at install time (section 8.6). |
| **Screen capture on the Air** while a suite page shows a real race or a bootstrap code (an agent's `screencapture` passes the preflight with no prompt; computer use) | Rule 5: no capture while a suite page or an `ssh lab-suite` window is open; Q-Y10 covers the Air before its first real race (section 8.6) | Conduct only; sessions in other repos never read this repo's AGENTS.md. A line in the Air's CLAUDE.md: asked of Yu on 2026-10-17, not answered (Q-Y10). |
| Browser extensions reading licensed data | A Private window, or a profile without extensions | Yu's choice. |
| Supply chain | No third-party Python or JS. A pinned, hash-checked upstream with an import-origin assertion. `-S` drops site-packages. | Homebrew python@3.13 itself. |
| Upstream drift widening imports or changing semantics | The import-closure test, the contract test, reviewed pin bumps | It still blocks work when it breaks, but loudly. |
| Accidental real betting | No live code in this repo, no credential path, FORBID_NETWORK, the audit hook with no off-switch, boundary tests | None in the MVP. |
| Crafted or corrupt data files | Hash of the exact bytes parsed, decompressed size checked against the manifest, tight bounded decompression, the strict reader, `book.py`'s own refusals | — |
| Licensed-data leakage (git, logs, error text, screenshots, model context, browser history, Spotlight, crash reports, SQLite temp files, exports) | Hygiene scanner and its four git hooks (pre-commit, pre-merge-commit, commit-msg, pre-push); synthetic-only fixtures and uisnap screenshots; error mapping; aggregate-only diagnostics; agents never read, search or list `~/betangel-data` or the install salt (rule 5); `.noindex`; `TMPDIR`/`SQLITE_TMPDIR` and `temp_store=MEMORY`; no-store; exports under `~/betangel-data` only | Human error, covered by review. The lab's home is not a git worktree, so a search from `~` walks into `~/betangel-data`, whose `raw/` paths carry market ids (Nuance, PR #1 review, item 3). Lab-Claude's file tools have deny rules for `~/betangel-data` and the install salt, which Yu approved on 2026-10-16 (Q-Y9); that a Read deny also covers Grep and Glob is still to be verified. For Bash, Nuance's SSH shell and Astra, rule 5 is conduct only. Analytics and Spotlight Privacy are Yu's decisions (Q-Y14, Q-Y15). |
| Interfering with Nuance's runs | No engine or real-data command while the run marker exists; the real-data lock Nuance's wrapper waits on; no automatic catalogue rebuilds | Until Nuance agrees the marker half of Q-N3 again, lab-Claude also runs no real-data command while a run is announced (section 6.8). |
| Agent or scope drift toward live features or automation | The suite's AGENTS.md, the closed route test, the OperatorClick test, synthetic-only `TestOrder`, the proposal process | — |

---

## 10. Safety invariants and how tests prove them

| ID | Invariant | Mechanism | Test |
|---|---|---|---|
| I-1 | No credential code path | Only `rx.py` imports betangel_research, and only from the allowlist | An AST test: `rx.py` is the sole importer, and imports only allowlisted names. A fresh-subprocess import of the full engine checks the closure: the 25 modules, and none of gateway, cli, auth, credentials, transport, api, esa, recorder, killswitch, arming, presence, reconcile, risk or capability. A static scan of **suite sources only** looks for `security` CLI or Keychain strings, Betfair hosts, `placeOrders`, `cancelOrders`, `replaceOrders`, `updateOrders` and `HeartbeatAPING` (the test builds these names by concatenation). The deps closure is checked separately, by its module set and by the absence of gateway order-method literals in those 25 modules. `constants.py:14-32` and `config.py:35` legitimately hold hosts and `"keychain"`. |
| I-2 | FORBID_NETWORK is always on | The launcher sets it. `guard.py` refuses to arm unless it is exactly `1` and no other `BETFAIR*` or `BETANGEL_BETFAIR_*` variable is set, and then refuses any change to it, to `TMPDIR` or `SQLITE_TMPDIR`, or to any such variable, and it refuses to start a child given an environment that lacks it or carries such a variable. `rx.py` also refuses unless upstream's `paths.network_forbidden()` is true. `guard.py` has no off-switch. | Engine start without it is refused. A stray variable is refused. Changing it, `TMPDIR` or `SQLITE_TMPDIR` after arming is refused, and so is a child started without it. An AST test finds no environment or config read that disables the guard. |
| I-3 | No outbound network, no name lookups | The PEP 578 audit hook (irrevocable), installed before any upstream import, refuses `socket.connect`, `connect_ex`, `sendto`, `sendmsg`, `getaddrinfo`, `gethostbyname`, `gethostbyaddr` and `getnameinfo`. The one exception: a connect to an absolute, normalised Unix socket path directly in the run dir, permitted before `seal()` with `permit_unix_connect` and matched by its exact text, with no NUL in it (the kernel ends the socket name at the first NUL), while the run dir still resolves where it did at `arm()` and the socket path is not itself a link (connect follows one). That is the control socket, which `stop` and the takeovers by `open` and `ssh-session` use, and an attached `ssh-session` keeps its permit after it seals (section 9.1). TCP connects stay refused.<br>**Residual: a hard-linked control socket** (Astra's re-review of #4). The check reads the name, not the socket behind it, so a hard link at `control.sock` to a socket that another process of this user made passes, and `stop`, `open` or `ssh-session` would talk to that socket. In Astra's terms: "acceptable within the documented same-uid/pre-existing-hard-link limit. The 0700 run directory and guarded hard-link operations address ordinary planting; the guard does not authenticate a socket's provenance. Rejecting `st_nlink > 1` would catch ordinary aliases, but would not prove provenance after another link was removed. Keep the residual documented." No code change; `guard.py`'s I-3 entry says the same. | `socket.create_connection(("192.0.2.1", 443))` (TEST-NET-1) raises before any packet. `getaddrinfo("example.com", 443)` raises. A second hook cannot remove the first. A connect to a Unix path that was not permitted raises, and so does one to a permitted path spelt another way (`run/x/../control.sock`), through a run dir replaced by a link, to a socket path that is a link, or to a path with a NUL in it (never permitted, and refused even if one is put in the hook's permits). A TCP connect to `127.0.0.1` raises too. A path permitted before `seal()` still connects after it, and no permit is accepted after it. |
| I-4 | Loopback only | The hook allows `socket.bind` only to `("127.0.0.1", port)` for a port permitted before `seal()` (`permit_loopback_port`) and to the control socket path in the 0700 run dir, permitted before `seal()` with `permit_unix_socket` and matched by its exact text, with no NUL in it (the kernel ends the socket name at the first NUL), while the run dir still resolves where it did at `arm()` and the socket path is not itself a link (bind follows a dangling one and creates the socket at its target). The hook allows `listen()` only on an AF_INET socket bound to 127.0.0.1 with a non-zero port (a permitted port-0 bind has its port by then), or on an AF_UNIX socket bound to a name (`listen_refused`; Nuance's PR #2 review, item 4; 01f6201). CPython raises no listen event, and `listen()` on an unbound AF_INET socket binds 0.0.0.0. So at the first `socket.__new__` event the hook puts a wrapper that raises `socket.listen` on `socket.socket.listen`. `arm()` does this at once if `socket` is already loaded, and never imports it. AF_INET6 is refused. So is making a socket whose class would not call the wrapper: a bare `_socket.socket`, or a subclass with its own `listen`. `arm()` refuses (`call_replaced_early`) if `socket.socket` already has a `listen` of its own. `getsockname` is asserted. | Binding `0.0.0.0`, the wrong port or another Unix path raises, and so does a permitted Unix path that is a dangling link. A Unix path with a NUL in it is never permitted. The server's address is `127.0.0.1`. A control-socket peer of another uid is refused. `listen()` on unbound AF_INET, AF_INET6 and AF_UNIX sockets raises `listen_refused`. These are tested on SOCK_DGRAM sockets, which never listen, so a miss cannot listen on 0.0.0.0. A port-0 loopback bind listens, before and after `seal()`. |
| I-5 | No subprocess after startup | Per guard mode, chosen by the command name only. Before `seal()`:<br>- **engine:** `git -C <abs dir under the suite roots> rev-parse --is-inside-work-tree` (paths.py:149, used by `validate_config` and `StatePaths`), its dir inside a root both as text and with its links resolved (Astra's re-review of #4), and one `/usr/bin/open http://127.0.0.1:<port>/#c=...`;<br>- **vendor:** exactly the five git argvs of `tools/vendor_research.py` (`cat-file -e` and `merge-base --is-ancestor` in the clone, then `clone`, `checkout` and `remote remove`), each with exactly `guard.VENDOR_GIT_ENV` plus HOME (section 3.5; Nuance's PR #2 review, item 10, and Q-N2; 816e832, 1d23fdc);<br>- **release:** local git on this checkout only, with `RELEASE_GIT_PREFIX` and exactly `guard.RELEASE_GIT_ENV` (no user or system git config, no replace refs or grafts; 972f555): the filter-driver config query, `ls-files --stage -z`, `status` (never entering a submodule), `rev-parse` of `<id>^{commit}`, `refs/heads/main^{commit}` or `<id>^{tree}`, `merge-base --is-ancestor` and `archive` of a full object id, never a tag or other name (cdda336);<br>- **uisnap:** the exact `swiftc` build argv;<br>- **test:** the test runner never seals. It starts only isolated interpreters (`-I -S -B`), this checkout's `bin/suite`, and local git under `TMPDIR`.<br>After `seal()`, `subprocess.Popen` and `os.posix_spawn` are refused in every mode, except uisnap's one binary, registered before `seal()` and started only while its sha256 is unchanged. In every phase and mode it refuses:<br>- `os.system`, `os.exec*`, `os.spawn*`, `os.fork` and `os.forkpty`;<br>- a direct `_posixsubprocess.fork_exec`, which `arm()` wraps so that it raises an event (`subprocess` keeps its own reference to the original);<br>- importing `multiprocessing` (any submodule), `concurrent.futures.process`, `ctypes` or `_ctypes` (`import_refused`), because `_ctypes` reaches libc through `dlsym` and `call_function` with no `dlopen`;<br>- `ctypes.dlopen`, `ctypes.dlsym` and `ctypes.call_function`, and SQLite extension loading.<br>`arm()` refuses if one of those modules is already loaded (`module_loaded_early`), and unless `subprocess._fork_exec` and `_posixsubprocess.fork_exec` are both the C original (`call_replaced_early`). Threads are unaffected.<br>**A check-then-use limit** (lab-Claude's reading, not a reviewer's finding). The git probe's directory (`engine_argv_ok`), the test runner's `git -C` directory (`runner_git_ok`), vendor's clone path (`vendor_argv_ok`) and release's `-C` checkout (`release_argv_ok`) are judged, links resolved, when the child is started. git resolves the path again when it runs, so a process of this user that changes a link on that path in between is not covered. `guard.py` lists it with the other same-uid limits. (Nuance's PR #2 review, items 3 and 18; 56a2631, 886d64b. The old text also implied that `os.system`, `os.exec*` and `os.fork` were allowed before `seal()`; they never were.) | Startup succeeds. After sealing, `subprocess.run(["/usr/bin/security", ...])` and `os.system` raise. Any other argv during startup raises, in every mode, and so does the engine's git probe through a link out of the roots. A uisnap binary that is unregistered, a symlink, or changed after registration is refused. `multiprocessing.Process.start`, `ProcessPoolExecutor.submit` and a direct `fork_exec` are refused before and after `seal()`, and in test and vendor mode, with nothing written outside the roots. `_ctypes.call_function(_ctypes.dlsym(RTLD_DEFAULT, "mkdir"), ...)` is refused. Startup git and threads still work. |
| I-6 | Writes confined | The single writer helper, plus the hook's write guard on `open` (write flags), `os.mkdir`, `os.rmdir`, `os.remove`, `os.rename` and `os.link` (both paths), `os.symlink`, `os.truncate`, `os.chmod`, `os.chown`, `os.chflags`, `os.utime`, `os.mkfifo`, `os.mknod` and `sqlite3.connect` paths: only the suite state roots of the HOME it runs under (test engines run under temporary HOMEs). Two guard modes add to them: `vendor` its deps root, this checkout's `pin/` and an `os.mkdir` of exactly the share dir, and `release` the app root (the release copies), which no other mode may write. The suite root under `~/betangel-data` is a write root for the engine only; the test runner, `uisnap`, `release` and `vendor` never get it, so tests, which use temporary HOMEs, cannot reach the real one. `TMPDIR` and `SQLITE_TMPDIR` are the same absolute path with no `.` or `..` component (so it differs from its normalised text at most by a redundant or final `/`), inside the roots both as normalised text and with its links resolved, with no link from its root down to it (8d0955d), and `temp_store=MEMORY` is set.<br>- `arm()` refuses a write root or `TMPDIR` that the file system puts in, around or onto `~/betangel-data` (`root_overlaps_data_home`), and an engine suite root that is not a real directory, or missing, at exactly `realpath(~/betangel-data)/suite.noindex` (`suite_root_misplaced`). It also refuses a placement it cannot judge, because a stat fails for any reason but a missing name (57fc0c9). The hook refuses a symlink, hard link or rename that takes the place of a root, `TMPDIR` or a directory between `TMPDIR` and its root (`root_replace_refused`; 8d0955d for the directories between). Section 3.7; Nuance's PR #2 review, item 1; 62c39c6, 851885a.<br>- It refuses removing, moving or replacing `run/realdata.lock`, and moving or replacing `run/` itself, which would carry the lock away (`run_lock_protected`; section 6.8; 18de53e, 6aeb1d5). `arm()` refuses a `run/` or lock that is a link (`run_lock_invalid`; b0d5c0d).<br>- `chmod`, `chown`, `utime` and `truncate` on a descriptor are judged by its `F_GETPATH` path, and refused without one (item 17; 59e2f22).<br>- Every SQLite connection is a guard subclass whose `setlimit` refuses `SQLITE_LIMIT_ATTACHED` (`sqlite_limit_refused`), and the hook refuses `sqlite3.connect` events not made by the guard's wrapper: a direct `Connection`, a re-`__init__`, a reference taken before `arm()`, a factory argument (`sqlite_connect_refused`; item 16; 3da0c26).<br>- `temp_store=MEMORY` is read back as 2, and `connect("")` is refused (item 15; 06dba20).<br>Defence in depth, not a sandbox. Same-process code can still call `sqlite3.Connection.setlimit` on a connection directly, set `temp_store` back with a PRAGMA, or call subprocess's private `_fork_exec` or `_socket.socket.listen` directly; neither the suite nor the pinned closure does. `guard.py` lists the other same-uid limits. | A session over fixtures under a temporary HOME-like root writes nothing outside the roots (tree diff). Nothing appears under `/tmp` or `/var/tmp` during a catalogue build or a session. Writes under a data root, or into a `path_guard` denied tree, raise. These are refused too: a root linked into, equal to or containing `~/betangel-data`, as written, through an alias, the firmlink, `/.vol` or another case; `suite.noindex` linked to a data root; a root linked into a data home that cannot be stat()ed when `arm()` runs; a link or rename onto a root, `TMPDIR` or a directory between them, and a `TMPDIR` with a link below its root; a `run/` or lock that is a link; `fchmod` on a read-only descriptor in the data home; `setlimit` on the ATTACH limit, and a re-`__init__` or a direct `Connection`; `connect("")`. A spilled temp table opens no `etilqs` file. `vendor` writes nothing else in the share dir, and only `release` writes the app root. |
| I-7 | No live route | The closed route table and command enum | Exact-equality tests and the forbidden-name test. |
| I-8 | Orders on real data come only through the operator-click code path. This is a code-path property, not proof of a human (section 7.1). | OperatorClick minted only in request handlers, with a fresh nonce and a valid session token. `TestOrder` and `ReplayedClick` are accepted only in synthetic mode. | An AST test checks construction sites and the callers of `PaperDesk.place`, `.cancel` and `.withdraw`. Nonce replay places nothing. A `TestOrder` on an engine with a real data root is refused. |
| I-9 | Licensed data never in git | `.gitignore`, the hygiene scanner, the pre-commit, pre-merge-commit, commit-msg and pre-push hooks, the fixture namespace | The scanner fails on planted `.bz2`, a large file and a `1.1xxxxxxxx` id, and on binary data past 8 KiB or without a NUL, base64, hex and `\xNN` copies of a bz2 member, a clean-filter attribute, tables split by CR, NEL or LS or behind a BOM, an id in a commit or tag message, and a file only in pushed history (Nuance's PR #2 review, items 5, 19, 20 and 21). After lab-Claude's round-4 review also: a blob or commit hidden by a replace ref or a graft (staged, range and push); pre-push input past 1 MiB (refused); a GIT binary patch, decimal byte lists, `od` output, a bytea literal, base64 of base64 and marker-led dumps of a bz2 member; box-drawing, HTML, LaTeX and fullwidth-bar tables, accented names and names in capitals; unquoted secrets in a file and a message. Near misses stay clean (a sorted price ladder, lists of small counts, marker-led name lists). After the round-4 recheck: lists of full 40- and 64-digit hashes, bare or after a marker, stay clean in a file and a message, while the same shape holding a bz2 member, a zlib or gzip stream or flagged text is still caught (2ae7640); 18 lines of 200 KB each scan within 10 s (805356c). After the round-4 finishing review also: an unclosed literal of escaped quotes on a 200 KB line, within 10 s (1be5dc1); data after one real hash line, and text with one NUL or 0xFF byte, in those layouts (287264a); a PNG or a PDF in those layouts, and raw deflate in more than 64 of those lines (b656145), while lists of 64 hashes stay clean. After the finishing review's recheck also: UTF-16 text, bare or with a BOM, in those layouts (fab0b92); a record of under 96 bytes with one NUL or 0xFF byte, in hex, base64, escapes or a decimal list, and in UTF-16 (53904f8); raw deflate in two runs of 64 of those lines, split by a blank line or a line of words (7126190), while lists of 8 and 32 hashes in one file, and 70 lines of a hash and a subject beside a list of 8, stay clean. After the recheck of 7126190 also, in a file and a message: raw deflate in base64 runs that each decode to a list of 64 or 40 of those lines, in 64 plain lines beside one such run, and in lists of two or four of those lines split by blank lines past 64 lines in all (bfd2f6a), while 64 hashes in lists of two or of four stay clean. Fixture-provenance test. |
| I-10 | Raw data read-only; no ingest or index by the engine | A read-only open. Suite code reaches upstream only through public `rx` names. | A synthetic data tree's hash is unchanged after a full session. `tests/test_ast_boundary.py` parses every module of the package, `bin/` and `tools/`. It refuses:<br>- the test-only names of section 4.2 and `index_archives`;<br>- any use of `rx` other than `rx.<namespace>.<public name>`, `rx.call(...)` and `rx.map_error(...)`: so no `rx._archive`, `rx.pin` or `rx.guard`, no `from .rx import ...`, and no namespace bound to another name. `rx` is any name an import binds to it, and any attribute named `rx` however its object was reached (`betangel_suite.rx`, `engine.rx`); `rx` is imported only from the package (`from .engine import rx` is refused), and the string `"rx"` is refused anywhere outside a docstring (`getattr(x, "rx")`, `x["rx"]`, `x.get("rx")`, `x.__getattribute__("rx")`, `operator.methodcaller("get", "rx")`), as is an `operator.attrgetter` path with an `rx` part (`"rx._archive"`);<br>- `__globals__`, `f_globals` and `__builtins__`;<br>- `.modules` on anything but `sys`, and on `sys` (a name `import sys` binds, or a `.sys` attribute such as `os.sys` or `rx.pin.sys`) anything but a literal read of a module outside betangel_research and betangel_suite that is not `sys` or `builtins`; `from <any module> import sys`; `getattr`, `vars` or `__dict__` on `sys`; and the strings `"modules"` and `"sys"` anywhere outside a docstring (`getattr(x, "modules")`, `x.get("modules")`, `x.__dict__["sys"]`, `object.__getattribute__(s, "modules")`), and an `attrgetter` path with either part;<br>- computed imports: `import_module` or `__import__` without a literal name, or with a literal argument that is relative, names betangel_research or betangel_suite, or is `sys` or `builtins`; any import by file or loader, `pkgutil.resolve_name` and `inspect.getmodule`; `exec`, `eval` and `compile`, as builtins or through the `builtins` module; the string `"builtins"` outside a docstring; and `from <any module> import builtins`.<br> Six exceptions are allowlisted with reasons: two `sys.modules` checks in `pin.py`, the file import of `tools/vendor_research.py` in `cli.py`, and, since phase0/foundation's round-4 fixes were merged, `guard._refuse_loaded_modules`'s read of the loaded modules' names (`module_loaded_early`) and `pin.py`'s closure finder and loader (`spec_from_file_location`, and the `SourceFileLoader` base of `_PinnedLoader`). A class statement's bases are reported under the class's name, so the last exception covers `_PinnedLoader`'s base list only; as the merge first added it, it named `pin.py`'s whole module level, where any computed import would have passed (round 4b's review). Planted violations are tested too, including each spelling a reviewer found on 3320143 and each one lab-Claude's round-3 review found on adb7c63, such as `from os import sys`, `__import__('sys').modules[...]`, `sys.modules['betangel_suite.rx']._archive`, `sys.modules['builtins'].exec(...)`, `engine.rx._archive` and `from .engine import rx`, and each literal-key or `attrgetter` spelling round 4b's review found on d00436e, such as `vars(engine).get('rx')._archive`, `os.__dict__.get('sys').__dict__.get('modules')`, `sys.__getattribute__('modules')` and `operator.attrgetter('rx._archive')`. Nuance's PR #4 review, item 7, found that suite code could reach `ingest_archive` "through rx._archive, sys.modules or `__globals__`" while the import tests stayed green. The rule reads names and literal strings, not values: code written to evade it, such as a computed `getattr` on a local that holds an upstream object, a name or key built at run time (`"r" + "x"`), an import by a route the rule does not name (`pickle`, say), or a module object reached through `gc` or a frame's locals, is not refused. |
| I-11 | No gated month ever replayed | `month_gate` on path and marketTime at catalogue time and at every open. A `None` month is refused as `month_unknown` first. | Synthetic members dated 2026-01, 2026-09, 2026-10 and 2027-01 are refused with the gate reason. A member with no parseable marketTime is refused as `month_unknown`. Research months are refused while no ruling is set. |
| I-12 | Spoiler-free | Catalogue field allowlist; the tap releases outcome values only at their pt | Planted outcome values never reach SQLite, a frame or the browser before CLOSED. |
| I-13 | Pin integrity, and never the moving clone | Per-file hashes over every `PINNED_FILES` entry, the origin assertion, `sys.path` append only. The pin stays at 76f71dc until a closure module the suite needs, or the month roles, change; Nuance reviews every bump that changes a `PINNED_FILES` entry, and the contract test gates it (Q-N1, Q-N2). The closure finder, the no-link reader, `read_pinned()` and vendor's pre-pass, its identity check against the clone and its `main`-only rule (section 3.5; Nuance's PR #2 review, items 2, 7, 8 and 22, and Q-N2; 1d23fdc, e51b469, e4ddc18, 7357273, 0a1c482, 923c1de, 08af945). | A tampered file in a temp copy gives `pin_mismatch`. `sys.path` never contains `~/betangel-research`, however an entry spells it: an entry that reaches the clone through a link before `..` (`alias/../sub`, or `alias/..`, which names the clone itself) is refused before any upstream import. That answers the pin finding in Astra's re-reviews of #2, #4 and #5: caa17e0 on phase0/foundation, which reached this branch in 5044c47, with its regressions in `tests/test_pin.py` (the `alias/..` cases from 9d3f54f). Origin-assertion test. Oracle tests never pass `~/betangel-research` as `repo_root`. A linked `research/` or a hard-linked pinned file gives `pin_mismatch` (both open paths), and a tree spelt with a final `/`, `/.` or `//` is refused (f77cf01). A FIFO never hangs. An unpinned `betangel_research` module is refused by statement, from-import, `import_module`, `__import__` and `find_spec`. A closure module changed after `activate()` is refused at load. The pinned files' imports stay inside the closure (AST). `vendor` writes nothing into a synthetic clone reached through a link (tree snapshot, empty directories included), refuses unmerged and dangling commits, and never changes a clone file's mode. A path linked through the firmlink or `/.vol` into a clone behind a directory with no search permission, or into a clone that is a link loop, is refused by `roots.lies_in` and by the guard's partial clone check (26fb4c4), and so is a path through a directory with no search permission that holds a link into the clone (4ddf966). |
| I-14 | Right interpreter | The launcher's absolute path; the version check | Only 3.13 and 3.11 are accepted; 3.12, 3.14 and 3.15 are refused. |
| I-15 | Paper fidelity | Exact mode, the yield tracker, position-based re-seeding | The parity contract (section 7.4), the yield-tracker oracle test, the no-look-ahead re-seed test, the full-cancel test, and `journal.verify()` for every session. |
| I-16 | Agents are not handed Yu's token or real rows by the code. This is a code-path property: the code never prints them, but a same-uid agent that disobeys rule 6 is out of reach. | Single-use codes printed only by `open` (to `/usr/bin/open`), `ssh-session` and `--print-url`; token in memory and registered with `secret`; aggregate-only diagnostics; error mapping; headless commands read real roots only from reviewed code (section 8.6) | Test runs capture stdout and stderr and assert no token or code pattern. Tests plant leaks (`os.write(1, ...)`, a child process, an id-shaped integer) on whichever route section 8.6 takes. On the reviewed-code route, a headless command carrying one, from a dirty checkout or a commit main does not contain, is refused before any real root is read. On the filter route, they never reach stdout or stderr. A `selfcheck` run over fixtures does not print the fixture's synthetic names or prices. A synthetic member with a bad hash or a truncated line produces no market-id or event-id pattern on stdout, stderr, `logs/` or HTTP. |
| I-17 | No engine during Nuance's runs | The run marker, checked before anything is written under `~/betangel-data` and on every tick. Nuance's wrapper creates it with O_EXCL and waits for `engine.lock`: "Wait at least 60 s for engine.lock, and fail closed if it is still held" (Q-N3; Nuance's PR #4 review). `run/realdata.lock`, which every real-data process holds shared, from before `TMPDIR` until it exits, with the marker re-checked under it, and which Nuance's wrapper takes exclusive: "The wrapper waits 60 s+ for LOCK_EX, failing closed" (section 6.8; Nuance's PR #2 review, item 6; 596d052, 18de53e, fbbc0c3). | A marker present at start refuses the engine, real-data commands, `vendor` and `bin/suite test` on both interpreters; only `stop` skips the check. An unreadable marker refuses them too. A marker appearing during a test run stops it before its next test, and the test helpers start no engine while the runner's real marker is present or unreadable; an engine a test already started runs until that test ends. A headless command running when the marker appears stops before its next member, and the wrapper's `LOCK_EX` waits for it. Stand-ins for `catalogue` and `selfcheck` show that a real-data command takes `LOCK_SH` before it creates `TMPDIR` and re-checks the marker under the lock. On phase0/http `serve` and `open` have their own: each refuses with `run_lock_busy` and `run_marker_present` under the lock before its `TMPDIR` or engine, holds the lock while its engine runs, and (`serve`, with a 2 s grace) lets the wrapper in after the grace and within 5 s more. On phase0/viewing `ssh-session` has its own since round 4b (e9729a6): attached, it lets the wrapper in within 10 s of the marker while the engine is still in its grace (45.55 s before e9729a6); hosting, within a 2 s grace; it refuses `run_lock_busy` before any takeover, and `run_marker_present` under the lock before its `TMPDIR` or `engine.lock`. `open`'s attach path hands on no URL once the marker appears. `test` and `uisnap` start while the wrapper holds `LOCK_EX`. The tests of `ledger-summary` and the headless commands come with their handlers (section 6.8, "Owed"). `stop` runs while the marker exists and the wrapper holds `LOCK_EX`, taking nothing and making no `TMPDIR`. A stand-in wrapper's `LOCK_EX` waits for a holder and fails closed at its deadline. A headless holder stops at its next member. The guard refuses removing or replacing `realdata.lock`, and moving or replacing `run/` (`run_lock_protected`), and any suite write in `lab-runs/`; `arm()` refuses a `run/` or lock that is a link (`run_lock_invalid`). A marker appearing mid-session freezes the engine with no writes (tree diff), and it exits within the grace period, releasing `engine.lock` within about 35 s. |
| I-18 | Yu's real-data viewing, and real-data output to agents, run reviewed code | Release copies with `RELEASE.json`, checked at every launch from a copy; a working checkout runs synthetic mode only; headless commands read real roots only from a release copy or a clean checkout of a commit main contains (section 8.6). In Phase 0 every engine refuses every data root, from a release copy too. | `serve`, `open` and `ssh-session` from a working checkout refuse a non-synthetic data root. `selfcheck`, `catalogue`, `diagnose` and `ledger-summary` from a dirty checkout, or from a commit main does not contain, refuse one too. A modified file in a release copy is refused. |
| I-19 | Pause unless watched | Stream-drop, visibility, heartbeat, stdin-EOF and SIGHUP detection, and a 60 s heartbeat timeout; grace and takeover; `max_session_s` for every engine | Dropping the stream cleanly, hiding the page, or closing stdin pauses the clock within 2 s. A silent disconnect is bounded only by about 3 min today. Owed before Phase 1b: no request from the playing controller for about 5 s pauses with `not_watched`, tested with a peer that reads and never closes (section 8.6). A takeover within the grace period keeps the session. Expiry marks it `abandoned` (the end reason, and `ended reason=abandoned` on the hosting `ssh-session`'s stdout). The fast tier uses tiny graces through the in-process seams; the heavy tier goes through `bin/suite` from a release copy, with the 60 s minimum grace. |

Review of `guard.py`, `rx.py`, `errors.py`, `release.py`, `runmarker.py`, `api/`, the launcher, the boundary tests, the hygiene scanner and pin bumps is routed to Astra; `engine.py` and `roots.py` go to Astra and Nuance jointly (section 3.9). Lab-Claude also proposes Astra for `cli.py`, uisnap and the staged scripts; that is open (Q-N12).

---

## 11. Testing strategy and tooling

- **Python.** stdlib `unittest`, run by `bin/suite test [--py311] [--heavy] [-v] [-k PATTERN] [-j N]` (section 3.6). It discovers tests as this would:
  `cd ~/betangel-suite && env -i ... BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.13 -I -S -B -m unittest discover -s tests -t .`
  It then runs each test module whole in one of N worker interpreters (default 3, at most 4; `-j 1` runs them in the runner itself). `tests/__init__.py` appends the deps clone through `betangel_suite.pin`. It runs on python3.13, and `bin/suite test --py311` runs it again on python3.11.
- **Unguarded children.** The runner's guard refuses every TCP connect and starts only isolated interpreters, this checkout's `bin/suite` and local git. So HTTP test clients run in, and `node` is started by, relay child interpreters (`-I -S -B`) that never import `betangel_suite` and so are unguarded (`tests/test_http_support.py`, `run_relayed` in `tests/__init__.py`).
- **Two tiers.**
  - **Fast** (*measured* about 47-48 s with 3 worker interpreters on the lab M1 under `nice -n 10`, on 3.13 and 3.11; about 61 s with `-j 2`; about 127 s serially): run on every change. It meets the 60 s target only in parallel. Every boundary and security test (I-1..I-8, I-16..I-19, HTTP group 6) stays in it. The default of 3 workers raises peak load on the shared M1, so use `-j 1` or `-j 2` when the lab is busy.
  - **Heavy** (opt-in, `bin/suite test --heavy`; *measured* about 90-95 s in all): in Phase 0, the real uisnap build and WebKit runs, the synthetic size test and the 60 s grace expiry through `bin/suite ssh-session`; later, parity seeds, the 200 random seek points and performance.
  - Neither tier starts while a Nuance run is announced. `bin/suite test` refuses both tiers, on both interpreters, while the run marker exists (`run_marker_present`, `run_marker_unreadable`; section 6.8; Nuance's answer to Q-N14). A run already going stops before its next test, or its next module, once the marker appears; the tests then running finish first. The helpers that start engines check the real marker again before each launch, but an engine already started runs until its test ends (section 6.8).
  - **Pre-commit.** `tools/pre-commit` runs only the hygiene scanner on the staged tree, not the tests.
  - Each run records its runtime (`runtime_s=... python=... tier=... jobs=...`).
  - A run fails with `refused:state_root_changed` if an entry appears or vanishes in the real state root outside `tmp/` while it runs (contents are not compared); only `run/` entries explained by an engine Yu starts or stops meanwhile, whose `run/engine.lock` is definitely held, are exempt (AGENTS.md, Phase 0 status F).
  - Oracle fixtures are capped at about 2,000 messages and 6 runners, because the oracles are slow: `run_paper_replay` takes 141 s and 1.98 GB on a 60k-message market.
- **JavaScript.** `~/.local/bin/node --test ui/tests/*.test.mjs` (built-in `node:test`, no npm), run by `bin/suite test` from `tests/test_ui_assets.py`. That test names every file, because `node --test ui/tests` (a directory) fails on node 24. It covers:
  - the tick map against a JSON export of `LADDER_CLASSIC`;
  - ladder window geometry, frame application and idempotency;
  - the key map (no conflicts, every key mapped to a command);
  - formatters that take integer pence and hundredths only;
  - stream reconnect with backoff.
- **uisnap (Phase 0).** `bin/suite uisnap [--seed N] [--out DIR]` (guard mode uisnap, `betangel_suite/uisnap.py`) builds `tools/uisnap/uisnap.swift`, one file, with the Command Line Tools' `swiftc`: no Xcode, no install and no Screen Recording permission. It snapshots its own view only.
  - **How it works.** It refuses any configured data root (`synthetic_only`), a running engine (`engine_running`) and the run marker. It starts a **synthetic-only** engine in its own process on an ephemeral port, and hands the URL to the binary on its stdin. The binary loads the page in a WKWebView and drives keys and clicks through JavaScript. If the engine stops first (a run marker, a stop request or an actor failure), uisnap stops the binary at once, so `engine.lock` is freed on section 6.8's timing. A stop request then ends as `engine_stopping`. A run marker ends as `refused:run_marker_present` and an actor failure as `refused:engine_failed`: the engine's own end raises them before uisnap prints its summary line.
  - **No window on screen.** The WKWebView sits in a window that is never ordered in, and that reports itself visible to WebKit (`OffscreenWindow`), because `requestAnimationFrame` needs that. The binary checks every 100 ms that it has no on-screen window, and has no Dock icon. Its navigation delegate allows only the engine's own `http://127.0.0.1:<port>/` page.
  - **Output.** The binary writes no file: it sends PNG and report records on stdout. `uisnap.py` validates them and writes six PNGs of the 1470×830 pt viewport at the display's backing scale (2940×1660 at 2x on the lab, *measured*) and a sanitised `report.json`, which lab-Claude reads. They go by default under `~/.local/state/betangel-suite/uisnap/out/<UTC stamp>/`, or in a missing or empty `--out DIR` inside the state root. An `--out` under the suite root is refused (`write_outside_roots`): only the engine's guard mode writes there. The build is cached under `uisnap/build/` (section 3.7).
  - **What it is for:**
    - in-browser tests that `node:test` cannot run (canvas, DOM, stream handling);
    - layout checks at the Air's Safari viewport (about 1470×830 pt);
    - the seed of the L1 shell.
  - *Measured:* a cold build takes about 40 s, with an explicit clang module cache under `uisnap/build/`, and a WebKit run about 15 s. The design spike also received chunked NDJSON at 100 ms pacing, with no permission prompt.
  - It runs in the lab's logged-in GUI session. The heavy tier runs the real build and WebKit runs in a temporary HOME.
- **CI-free.** No hosted CI. Tests run on the lab, and Nuance can run them on the Air.
- **Fixtures.** `betangel_suite/synthetic.py` generates, and `tests/fixtures/gen.py` writes, synthetic PRO-shaped streams (reserved ids) with images, suspensions, removals, version changes, in-play and CLOSED. Traded volume only rises, so there is rising trd after any re-seed point. The `nonfinite_sp` option writes non-finite `spn` and `spf` strings and a non-finite `spl` size, and `no_market_time` writes markets with no marketTime. It does **not** yet write 503 windows, trd dips, non-finite `spb` or `spl` prices, or settlement zeroing (section 11.1). `no_ladder_definition` writes definitions with no `priceLadderDefinition`, and nothing else changes (section 7.1). Also:
  - a synthetic TAR in the documented member layout (month 2015-05), run through the vendored `ingest_archive` and `index_archive` into a temp root, so the catalogue and reader are tested against real research code;
  - variants the month gate must refuse: 2026 and 2027 members by path, a 2026-01 marketTime under a 2015-05 path (refused by ingest's content scan), and the same with its `marketTime` keys escaped (stored by ingest, and refused only by the index).
  
  Real markets are larger than random walks (5-44 runners, 721-6,166 book entries), so the generator also takes size parameters from the section 6.7 aggregates.
- **Test groups:**
  1. **Boundaries:** AST, import closure, audit hook, launcher (including the SSH checks before `env -i`) and environment refusals, route table, OperatorClick and `TestOrder`, release copy, run marker (I-1..I-8, I-17, I-18).
  2. **Data:** catalogue fields, the outcome leak test, research months not written, head and manifest checks, integrity and `decompressed_bytes` refusal, the truncated member, reader parity with `market_index._messages` (including a `not_json` line straight after a multi-message pt batch), month gate, `month_unknown`, roles from the pinned contract, error mapping (no ids in any output).
  3. **Replay:** yield-tracker parity with `snapshots_from_recording`; seek determinism (snapshot `canonical_sha256` after `seek(t)` equals a linear replay to t); checkpoint restore, including the high-water tracker; atomic pt batches; SP tap timing; SP non-finite invalidation shown.
  4. **Paper:**
     - the parity contract, including pending orders at CLOSED and at the end of the member;
     - the conservative property and the no-look-ahead re-seed;
     - the full-cancel test (EXECUTION_COMPLETE, never UNKNOWN);
     - a click followed by STOP, Esc, Z, X, Shift+Esc or void within 500 ms: the order ends REFUSED with the withdrawal reason and never activates;
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
- **Manual acceptance.** After each phase, Yu works through a written checklist in Yu's direct channel (section 3.9): keys, latency, readability on the Air through the tunnel. The checklist is a log of Yu's checks; acceptance is Yu's own words in that channel.
- **Review gates.** As routed in section 3.9. Lab-Claude never accepts its own Collab edit tasks.

### 11.1 Known gaps

Gaps in the synthetic fixtures and the Phase 0b engine, recorded from Nuance's PR #4 review (2026-10-16), with the phase each is owed before. The fix is Nuance's suggestion unless the row says otherwise.

| Gap | Why it matters | Owed before | Fix |
|---|---|---|---|
| **The in-play flip has one fixed shape** (Nuance, item 5). A synthetic market always flips in play at exactly the published marketTime, which is never revised, with no SUSPENDED at the off. `tests/test_synthetic.py`, `tests/test_integration_ui.py` and `tests/test_engine.py` lock that shape in. The real flip shape is unverified. | Phase 1a's countdown is accepted on synthetic data (section 12). The engine takes `ms_to_off` from the latest marketTime, while section 6.1 anchors the jump marks on the first-published one. In Nuance's early-start probe, 1,114 in-play rows had `ms_to_off` > 0. | Phase 1a | `Spec` options `off_offset`, `market_time_revision` and `suspend_at_off`. |
| **No 503 windows** in the fixtures (Nuance, item 6). | The yield tracker's parity test needs windows to enter, sit inside and leave (section 6.2). | Phase 1a | A generator option that writes 503 windows (lab-Claude's proposal; Nuance asked that this gap be listed, owed before 1a). |
| **No trd dips** in the fixtures (Nuance, item 6). | The conservative-parity property needs traded volume that falls and recovers (section 7.4). | Phase 1b | A generator option that writes trd dips (lab-Claude's proposal; Nuance asked that this gap be listed, owed before 1b). |
| **No non-finite `spb`/`spl` prices and no settlement zeroing** in the fixtures (Nuance, item 6). | Nuance: "Upstream has not shown that several of these occur in PRO files at all (F54; data-audit.md:36). There is no current risk, since the engine opens only Spec(seed)." | Not set | Lab-Claude's proposal; Nuance gave no fix for this gap: decide once the first PRO ingest shows whether they occur (counts only). Nuance's optional extra, not done yet: one engine test that opens an option market through the engine's `synthetic=` seam. |
| **`ladder()` promotes deeper levels, and the ladder type is ignored** (Nuance, item 10; latent, real data only). `engine.ladder()` drops an off-tick or sub-penny level, so the next level shows as best. `build_frame` never looks at the ladder type, so a FINEST market renders with `invalid_reason` None. A test pins that a keyless synthetic market (`no_ladder_definition`) gives the CLASSIC market's frame. | Synthetic markets are on the tick ladder, and CLASSIC unless `no_ladder_definition` drops the key, so the first cannot happen yet. On real data the grid could show a deeper level as the best price. | Real data (Phase 1a) | Flag a non-CLASSIC or missing ladder type in its own field, and keep a sub-penny level instead of promoting past it. |
| **The definition tap ignores the cache's keep and reset rules** (Nuance, item 11; latent, real data only). `_apply_batch` keeps the last definition of each message. With duplicate images in one message, the cache keeps the highest version (book.py:224-236; F54). | The frame can then mix two definitions: names and order from one, the book from the other. Synthetic messages hold one change each, so it cannot happen yet. | Real data (Phase 1a) | Mirror the cache's rules for each message. |
| **The ladder type is never shown** (Nuance, item 12; follow-up). market_index.py:147-154 does not track `priceLadderDefinition`. A definition without it renders normally, but V9 would refuse every click on that market in Phase 1b. Whether PRO files carry the field is unverified. | Yu could practise on a market where every paper click is refused. | Real data (Phase 1a) | Add selfcheck counts of markets with and without the field (counts only). |

---

## 12. Phases

**How to read the estimates.** Estimates are *lab work* in weeks; review waits come on top. Each phase has two exits:

- a **lab-done** exit: tests green and a synthetic demo;
- a **review-accepted** exit.

Lab-Claude continues on stacked branches while reviews queue. Lab-Claude also carries other workstreams (agenttool, Kingdom, Cloudflare), so it is not a dedicated developer.

| Phase | Scope | Lab-done exit | Review-accepted exit | Estimate (lab work) |
|---|---|---|---|---|
| **0: Scaffold, governance, pin, guards and viewing** (lab, synthetic only) | **Governance and pin:** the suite's AGENTS.md, README and this document; `pin/betangel-research.json` and `tools/vendor_research.py`.<br>**Engine and guards:** the launcher (SSH checks before `env -i`); `guard.py`; `rx.py` with error mapping; `roots.py`; `release.py`; `runmarker.py`; the hygiene scanner and its git hooks.<br>**Fixtures:** the synthetic generator, including the synthetic TAR through the vendored ingest and index.<br>**HTTP:** the skeleton (bootstrap code, token, Host, Origin, CSP, closed routes, HTTP/1.1 chunked stream) streaming one synthetic market's best prices.<br>**Viewing:** `ssh-session` with pause-unless-watched, heartbeat and takeover; `bin/suite release`; the staged viewer-key and sshd drop-in script; the Air-side self-test; `tools/uisnap`.<br>**Tests:** I-1..I-14 and I-16..I-19, with I-8, I-11, I-12 and I-16..I-19 in part only (synthetic mode, and the commands Phase 0 builds); the rest is in the 1a and 1b exits.<br>**Coordination:** the Phase 0 packet to Yu (R-1..R-7, Q-Y8) and to Nuance (Q-N1..Q-N5, Q-N12), and a Collab coordination task. | Tests green on 3.13 and 3.11. The closure is the 25 allowlisted modules. The hook refuses TEST-NET. A tampered pin is refused. Nothing is written outside the roots. uisnap PNGs of the synthetic ladder. **M1: Yu sees a synthetic ladder** on the lab screen (*target 2026-10-29*); from the Air once R-2 is installed, the Phase 0 stack is merged and Yu has released it (section 8.6). | Nuance agrees the allowlist, pin, state root and **run marker**. Astra has reviewed the guard, boundaries and launcher. Yu has answered the packet. | 1.5-2 weeks |
| **1a: Data layer, catalogue and read-only replay ladder** | Discovery of indexed roots; head and manifest checks; the spoiler-free catalogue (roles by `market_month`, research months not written); the verified in-memory member reader with the tighter limits; the yield tracker, checkpoints on the new schedule, clock and frames; the SP and definition tap. UI: picker, canvas ladder, one-click grid, countdown, banner, replay controls, chart strip, problem reports. The viewed-markets ledger and `ledger-summary`. Synthetic first. Real-data checks are counts only. | The synthetic UI is complete and accepted through uisnap and Yu's checklist **without PRO**. Real BASIC checks (counts only, from a release copy or a clean checkout of a commit main contains; section 8.6): the catalogue shows 12,200 engineering-year WIN markets, hides research months and holds no outcome fields; 200 BASIC members pass the reader smoke. Reader and yield-tracker parity pass, as does seek determinism. I-11 and I-12 are tested in full (catalogue, reader and tap). I-16, I-17 and I-18 are tested in full for the headless commands (`selfcheck`, `catalogue`, `diagnose`, `ledger-summary`): planted leaks, one I-17 test per command with the real-data lock, the ledger write freeze, and the reviewed-code gate. | Nuance reviews the data path. Yu accepts the synthetic UI. | 2.5-3.5 weeks |
| **M-PRO: first real PRO race** (its own milestone) | Needs Nuance's PRO ingest and index (Q-N4). Ingest and index are single-threaded and read every line of every member: about 100 GB decompressed and about 380M lines, so *inference* about 1.5-3 h of CPU. The run marker covers it. | PRO catalogue built (counts only); open budgets met on real members (p99 ≤ 2 s, max ≤ 8 s); the SP non-finite counts recorded; Nuance's `priceLadderDefinition` count on the PRO definitions recorded (counts only; section 7.1). Yu watches a real PRO race from T-10 to CLOSED at 1-10x, on the lab screen or through the tunnel, from the release copy. | Yu's acceptance. | Dated once Nuance gives an ingest date; about 2-3 days of lab work after that |
| **1b: Paper trading** (after R-1, R-6 and R-7; real-data journal writes only once the run marker is agreed; conditional on Nuance's ladder-key count, section 7.1) | PaperDesk with OperatorClick, and `TestOrder` in synthetic mode only; `validate_place`; exact mode with position-based re-seeding; activation, including at CLOSED and at the end of the member; cancel with the correct split, pending withdrawal and keys; STOP; lapse at the off and at close; settle at 2%; positions, exposure on both bases, green-up; the queue tracker; Rule-4 official and indicative figures; journals, `commands.jsonl`, sessions, attempts and void; the live v1 shadow badge; cap profiles; the debrief. With R-7 = ladder trading: exploration mode (replace, drag, size reduction). | The parity contract and conservative property hold; `journal.verify` passes for every session; deterministic synthetic re-run; the arithmetic and exposure property tests pass; the withdrawal and full-cancel tests pass; the 5 s `not_watched` pause test passes (section 8.6), which completes I-19; I-17's mid-session freeze is tested with journal writes; I-8 is tested in full (`PaperDesk` and `OperatorClick`); the re-seed test of Q-N7 passes. Real paper clicks pass V9's ladder check: Nuance's count finds the key present, or U-10, and any V9 ruling by Yu under D-5, has landed (section 7.1). | Nuance and Astra review the paper path. Yu completes 10 practice races with no confusing refusal or mismatch and confirms the keymap. | 3-4 weeks |
| **1c: Practice log, polish and MVP sign-off** | Practice log and CSV export; sounds; keymap overlay and settings; market overview; exploration mode if not already in 1b; docs (data-handling, keymap, threat model). | No data-hygiene findings in the scanner. MVP tagged. | A week of short sessions by Yu and a written feedback round. Release copy installed. | 1-1.5 weeks |
| **Total to MVP** | | | | **about 8-11 weeks of lab work, plus review waits** |
| **Later L1: native macOS shell** (before any live click) | A SwiftPM executable (AppKit, WKWebView with `WKWebsiteDataStore.nonPersistent()`, `WKURLSchemeHandler` `suite://`), grown from uisnap.<br>**It runs on the Air**, and reaches the lab engine with no forwarding: the forced command `suite ssh-session --stdio` bridges the SSH channel's stdin and stdout to the engine's Unix socket. The viewer key then becomes plain `restrict`, with no port-forwarding.<br>The browser TCP tunnel stays only for the browser MVP.<br>It is built on the Air from the reviewed merge SHA: the Air has the Command Line Tools 26.4 and Swift 6.3.0 (Nuance, Q-N13). There is no lab-build fallback. It is ad-hoc signed for arm64 (M2). There is no Xcode, Apple ID or distribution.<br>Menu-bar STOP. Global hotkeys need Accessibility or Input Monitoring, which only Yu can grant. | Every MVP feature works with no TCP port open on either machine (`lsof`). A peer from another uid is refused. A tested deny-all content rule keeps the page from reaching any Air loopback port (section 8.6). | Astra's security review; Nuance agrees the Air-side install. | 2.5-4 weeks, including the Air-side install, which depends on Nuance and Q-N13 |
| **Later L2: delayed stream on the Air** (Nuance-owned) | An Air-side package, in a separate repo never cloned on the lab, reuses the suite UI against a delayed-stream view or Air recordings, for integration only. DELAYED banner; 3 levels, 180 s conflation (constants.py:164-167), so practice value is low; recorder ceiling 180 markets (constants.py:216). DELAYED is the only paper source on the Air. Recordings never come to the lab. | An Air session with 0 orders and the DELAYED banner. The lab stays credential-free. | Nuance and Astra. | 1-2 weeks (Nuance) |
| **Later L3: live stage-and-type within D1-D5** (Air, after the £499 key and gate G1) | The suite shows the exact `cli.py place` command and the `presence.order_echo_line` text. Yu types it in Yu's own Terminal at `/dev/tty`. The gateway fetches its own live book and runs every check. The suite never types keystrokes or automates Terminal. A live-journal display would need P-12. Live-key market data is shown only in sessions that place real bets, never for paper (section 2.3).<br>**G1:** buy the key (Yu has committed to it); before buying, ask Betfair Developer Support whether low-volume betting from a mostly-viewing ladder risks read-only deactivation; set a website loss limit and confirm it covers Exchange losses; Nuance runs the outstanding live T-tests. | The first live orders are journaled and reconciled within the default caps, and Yu has reviewed them. | Yu. | 1-2 weeks of suite work, plus Nuance's testing |
| **Later L4: policy-gated live one-click** | Only after P-2..P-6 are approved. Native shell only, never a browser tab. Orders still go through `gateway.py` with an `operator_gui` source. | Each amendment has Nuance and Astra review and Yu's written approval. Upstream boundary tests updated by Nuance. | Staged rollout at minimum caps. | 4-8+ weeks, mostly upstream |
| **Later L5: automation research** | Offsets, timed fill-or-kill, stops, trailing stops and auto-green as simulated intents on historical replay. They need P-1, or they live inside `betfair/backtest` (Nuance). The rule engine has no order sink other than paper. | P-1 approved, or a backtest-side design. | — | Not estimated |

**Phase 0 status (2026-10-15).** Phase 0 is built on three stacked branches, synthetic only, and pending review:

- `phase0/foundation` (0a): the pin, guard, launcher, roots, run marker, `rx.py` and the hygiene scanner;
- `phase0/http` (0b): synthetic replay, the loopback HTTP API, `serve`, `open`, `stop` and the browser UI;
- `phase0/viewing` (0c): every Viewing item above, built and tested: `ssh-session` with pause-unless-watched, heartbeat and takeover; `open --print-url` and `claim_control`; `bin/suite release`; the staged viewer-key and sshd drop-in script; the Air-side self-test; `tools/uisnap`. It also brings the parallel test runner and the heavy tier.

The review-accepted exit, the first release copy (Yu's) and the viewer install (R-2) are still to come. AGENTS.md (Phase 0 status) lists the Phase 0 adaptations.

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
| Kill / stop | Cancel all | **Must** | MVP: paper STOP (UI, key, CLI), which also withdraws pending orders. The real kill switch (`killswitch.engage`) comes later on the Air. |
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

Nothing becomes more permissive by configuration alone. **The MVP needs none of these** (subject to section 7.1's ladder-type condition). R-1..R-7 (section 2.2) are rulings on this repo's design, not rule changes.

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
| U-10 | Only if Nuance's count finds `priceLadderDefinition` missing from the PRO definitions (section 7.1): a fact row, and a CLASSIC default only at the book.py:459 call site, for historical ODDS markets. Nuance's (PR #1 review, item 1). Any change to V9 itself goes to Yu under D-5. |

---

## 15. Open questions

### 15.1 For Yu

**Phase 0 packet (one page):** R-1..R-7 (section 2.2) and Q-Y8. The other questions are deferred to the phase that needs them.

| ID | Question | Needed in |
|---|---|---|
| Q-Y1 | **R-1.** May the suite drive `PaperExchange` directly, outside the gateway, for paper orders you click on historical replay? Nuance asked for your ruling. betangel-research's own batch replay already does this. The alternative imports the credential-bearing gateway. | Phase 0 packet (answered 2026-10-15, section 2.2.1) |
| Q-Y2 | **Viewing (R-2).** Recommended: the forced-command tunnel key plus the sshd drop-in, which you install yourself; lab-Claude stages them. In a Safari Private window, replayed prices appear on the Air's screen and in browser memory only. In a normal window, Safari History and iCloud would also sync the URL and title. Is viewing on the Air fine as personal use? | Phase 0 packet (answered 2026-10-15, section 2.2.1) |
| Q-Y3 | **Commission label (R-3).** You said "Basic 2%". `user_package_verified` on your word, or `user_package_unverified` until you have checked My Account? <br>**Asked of Yu in the packet, not answered.** Until you pick, the stated default `user_package_unverified` stands (section 2.2.1). | Phase 0 packet |
| Q-Y4 | **State root (R-4).** Is `~/betangel-data/suite.noindex` OK for practice journals, the catalogue and exports? | Phase 0 packet (answered 2026-10-15, section 2.2.1) |
| Q-Y5 | **Practice defaults.** Start at T-10 min; 2x until auto-slow at T-3; pause at the off? One-click on by default, or confirm every order at first? | 1b |
| Q-Y6 | **Practice loss limit** of £20 a day (£200 under the `practice` profile; its definition is in section 7.2): useful or annoying? | 1b |
| Q-Y7 | **Research-corpus months** (2023-2025): keep them hidden (the default, which protects later research)? Or open them, which needs a ruling id with Nuance and Astra and is logged? | Later |
| Q-Y8 | **Repo workflow.** Lab-Claude pushes branches and opens PRs that Nuance or Astra review (routing in section 3.9). Who merges: you, or lab-Claude after review? May UI-only PRs go on your acceptance alone? <br>**Answered by Yu on 2026-10-16:** "Its all good :) Merge when sensible". Section 2.2.1 records it, with lab-Claude's reading of "sensible", labelled as lab-Claude's. It was not one of the 2026-10-15 answers. An earlier version listed it there, with "Yu can veto or revert any merge"; Nuance found no source for that sentence or for the merge half, and pointed to section 3.9's recommendation as the source of the UI-only half (Nuance's PR #1 review, item 10). **The UI-only half: asked of Yu in the packet and again on 2026-10-17, not answered.** Lab-Claude's reason for keeping it open: this line asked it with no recommendation, and your 2026-10-16 answer does not take it up separately. **Asked of Yu on 2026-10-17, not answered:** Nuance's governance row for rule documents (section 3.9; Nuance's PR #1 review, item 9), with Nuance's PR #2 addition, "changes to AGENTS.md's rules or routing also need Yu". | Answered 2026-10-16, except the UI-only half and the governance row |
| Q-Y9 | **Agents and data.** Confirm that agents never see real rows, the viewed-markets ledger or real-data screenshots. **Caveat:** your OK alone cannot make an exception. A model context counts as an upload. The licence prohibits "the use of the Historical Betfair Data by, another organization or individual" unless "a specific agreement in writing with Betfair exists", and Betfair has not ruled on model providers (proposal 001, sections 5.1-5.2; Astra is run by OpenAI). Recommended (Nuance, PR #1 review, item 2): agents never read real values; you describe the shape, or a code-only `diagnose` check runs; real fields only with Betfair's written agreement naming the provider, plus your OK each time, scoped to one problem report and named fields. Until then exceptions are not available (rule 5; section 8.7). **This reworded question: asked of Yu on 2026-10-17, not answered.**<br>**Deny rules: asked of Yu on 2026-10-16, and approved** ("yes go ahead :) approved"). Nuance recommended them (PR #1 review, item 3), so that lab-Claude's file tools cannot read, search or list `~/betangel-data` or the install salt. Lab-Claude's Claude Code settings on the lab now deny `Read` and `Edit` of `~/betangel-data`, of everything under it, and of `~/.local/state/betangel-suite/install-salt*` (checked 2026-10-16). That a Read deny also covers Grep and Glob is still to be verified on the lab. Bash, Nuance's SSH shell and Astra stay conduct-only. **Asked of Yu on 2026-10-17, not answered:** the optional `~/.ignore` with `/betangel-data/` (Nuance's suggestion). Lab-Claude's recommendation is not to add it: it would also hide the folder from your own searches, and the deny rules already cover lab-Claude's file tools. | Before 1a |
| Q-Y10 | **Screen Recording: recommended No.** It would be granted to the host terminal (iTerm2) and cover every process under it, and `screencapture` takes the whole display. Any real race on the lab screen would then go into model context, which counts as an upload. `tools/uisnap` gives lab-Claude synthetic screenshots without it. If you still want it, capture would go only through a suite subcommand: that subcommand starts a synthetic-only engine, captures only its own window (`screencapture -l <id>`), and refuses while a real-data engine runs. You would revoke the permission when it is not in use.<br>**The Air too** (Nuance, PR #1 review, item 6). This question also covers the Air, before its first real race. There an agent's shell already passes the screen-capture preflight with no prompt (section 8.6). **Asked of Yu on 2026-10-17, not answered:** a line in the Air's CLAUDE.md that no agent captures the screen while a suite page or an `ssh lab-suite` window is open. Nuance recommends it. | Lab: not needed. Air: before its first real race |
| Q-Y11 | **Browser.** A Safari Private window for the suite on both machines (recommended), or a dedicated profile with no Betfair login, no extensions and no iCloud sync? Also, in the lab's Safari: sign out of historicdata.betfair.com, and delete saved betfair.com passwords and betfair.com site data, now rather than after the downloads (mailbox B4 asks for both; Nuance, PR #1 review). <br>**The clean-up now: asked of Yu on 2026-10-17, not answered.** | Now (the clean-up); 1a (the browser) |
| Q-Y12 | **Backups.** Is `~/betangel-data` backed up, for example by Time Machine? Journals and exports are licensed derivatives, so where copies go matters. | 1b |
| Q-Y13 | **Ladder.** Higher odds at the top or the bottom? Keep Bet Angel's keys (Z/X, C)? | 1a |
| Q-Y14 | **Analytics.** Mac Analytics auto-submit is on, so a native crash report from python3.13 or Safari could carry data to Apple. Turn sharing off? This is a privacy setting only you can change. | 1a |
| Q-Y15 | **Spotlight.** Add `~/betangel-data` to Spotlight Privacy? The suite root is already `.noindex`, but the data roots and index JSONL are not. | 1a |
| Q-Y16 | **PRO ingest timing.** The PRO year goes to a separate root and leaves P0's BASIC descriptor untouched. May Nuance ingest it before c2b3b3 lands, if Nuance agrees? <br>**Closed as moot** (Nuance asked for this in Nuance's answer to Q-N4): c2b3b3 is merged. The ingest has no date; it comes after the runbook's section 10.1 releases the TAR, under the run marker, and you are told. | Closed |
| Q-Y17 | **STOP from a read-only tab** (from the Phase 0c build). As built, a read-only tab cannot STOP: its button is disabled, Q is ignored, and the server answers 409 `not_controller` (section 9.2 item 8). Section 8.2 item 8 says STOP is always reachable by key. `bin/suite stop`, and claiming control first, still work. Should a read-only tab be able to STOP? Allowing it changes an `api/` authorisation rule, so Astra gave a view first (Q-A1): "a narrow authenticated, idempotent safety-stop exception is acceptable in principle. It should grant no other controller powers and retain the existing request checks. Yu decides" (re-review of PR #5 at d9b129e). It matters more in Phase 1b, where STOP withdraws pending paper orders. **Open for you.** Until you rule, a read-only tab cannot STOP. | Before Phase 1b |
| Q-Y18 | **Who makes release copies** (from the Phase 0c build). `bin/suite release <merge-sha>` refuses to run from a release copy, on a dirty tree, or for a commit that local main does not contain, but it cannot tell you from an agent, and rule 6 does not list it. AGENTS.md says making the first release is your decision. Phase 0c's draft of AGENTS.md also said agents never create one; that was left out, because it would be a new rule. Should rule 6 list `release`, or may lab-Claude make a release after review, as it merges PRs? | Before the first release |
| Q-Y19 | **Air-side files in this repo** (Codex review of PR #5). AGENTS.md rule 1 says "No credentials, Betfair API, network or live code ... Later live and Air-side code never lives in this repo"; section 3.9 rule 1 says the same ("Later live and Air code never lives in this repo"). The Air-side sentence speaks of later code, as it does in sections 0, 1.2 and 3.1, while section 8.6 and section 12 have lab-Claude stage two Air-side files for Phase 0: `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`. The real conflict is the unqualified "network code" clause: the self-test is a LAN SSH client, and the snippet configures the Air's end of the SSH tunnel. Options:<br>**(A)** move both to a separate private repo owned by Nuance: rule 1 holds word for word, but the port and Host block are kept in two repos, that repo does not exist yet (Q-N13), and Nuance has to agree to own it.<br>**(B)** keep the Host block only as text in section 8.6 and replace the script with a checklist: no Air code here, but a hand-read checklist loses the script's evidence rule (refused only when the key logged in and the lab refused) and its `ssh -G` preflight.<br>**(C)** a narrow written exception to rule 1's network clause for `tools/stage/air-*`: Yu-run, no credentials, no Betfair API, LAN SSH to the lab with the viewer key only, never run on the lab except under the test fakes. It keeps the tests and one source for the constants, but it is an exception to a binding rule, which rule 10 sends through the proposal process (a `docs/proposals/NNN-<slug>.md`, review by Nuance and Astra, and your written approval).<br>**(D)** you record that the R-2 approval already covered the section 8.6 Air files, and rule 1's network clause is reworded to exclude them: a clarification rather than a widening, because the Air-side sentence covers only later code and the draft you approved already had lab-Claude stage both files (section 8.6), though the recorded R-2 ruling names only the viewer-key script and the drop-in. It still rewords a binding rule, so it may need the same proposal process as C.<br>Lab-Claude recommended C or D, with the Air files taken only from GitHub at the reviewed merge commit's SHA (section 8.6).<br>**Answered: D** (Yu, 2026-10-16: "Go for D"; section 2.2.1). Rule 1's reworded network clause (section 3.9, AGENTS.md) is in proposal 002. Asked by lab-Claude whether a rule 10 proposal file is also wanted for D, Yu answered on 2026-10-16: "yes to formal proposal". It is `docs/proposals/002-air-viewer-files.md`, a draft for review by Nuance and Astra; Yu is then asked to approve the reviewed proposal in writing (section 2.2.1). PR #5 does not merge before Yu's written approval of the reviewed proposal 002 (lab-Claude's commitment, not Yu's words). Proposal 002 also asks you how to settle the lab's LAN address, which the two files name (its section 10). That was asked on 2026-10-16 and is not answered yet.<br>Astra's re-review of PR #5 at d9b129e (Astra's words, not yours): "**P1, Air-side rule conflict — resolved.**" and "I accept the narrow wording as implementing Yu's D ruling and do not reopen the resolved P1." That acceptance covers d9b129e's wording, not the current one: c051b2d, the next commit, added proposal 002 and changed rule 1's caveat sentence and its limits text (proposal 002, section 4.4). Astra's review of the current wording and of proposal 002 itself is still asked. Nuance's PR #1 review answered Q-N15 on c051b2d's wording, which is the current one (the Q-N15 row). | Answered 2026-10-16 (D). Proposal 002 is in review; the lab address is open |

### 15.2 For Nuance

**Phase 0:** Q-N1..Q-N5, Q-N12, Q-N14 and Q-N15. The others are deferred to the phase that needs them.

Nuance's PR #1 review (2026-10-16) answered Q-N4..Q-N11 and Q-N13, and, at the phase0/viewing tip of then (c051b2d), Q-N14 and Q-N15. The answers below are Nuance's, and Yu can override them. Nuance's PR #4 review answered Q-N1..Q-N3, and Q-N12 only in part: the merge rule and the routing rows Nuance asked for are answered and recorded, while the governance row for rule documents (asked of Yu on 2026-10-17, not answered) and the reviewer of the fail-closed row (asked of Nuance on 2026-10-17, not answered) are still asked, and how review requests arrive is not answered. The rows below record those answers, and Q-N3's row also records how Nuance's PR #2 review made it conditional again. Q-N14 and Q-N15 are asked only on phase0/viewing, this branch: Q-N14 is answered (its row, section 6.8 and AGENTS.md, Phase 0 status E), and so is Q-N15's wording; the rest of Q-N15 stays open for Nuance's review of proposal 002 (its row).

| ID | Question | Needed in |
|---|---|---|
| Q-N1 | Do you accept the engine importing only the 25-module closure in section 4.1, with no risk or capability? Will you treat the contract-tested names (section 4.5) as an interface and flag breaking changes in PR descriptions? Is test-only use of `risk` as an oracle acceptable under INTERNAL_ONLY? <br>**Answered by Nuance** (PR #4 review, 2026-10-16):<br>- Closure: accepted. Exactly 25 modules load (section 4.1). Before Phase 1b, `rx.py` gains wrappers: `StatePaths` with explicit roots, `OrderJournal` with `mode="paper"` and an explicit clock, and `validate_place` forced to paper. `SystemClock` is dropped from the allowlist; no suite code used it.<br>- Contract test: "yes, narrowed". `tests/test_upstream_contract.py` exists (d24193e), with Phase 0's names first, and gates every pin bump (sections 3.5 item 5 and 4.5).<br>- `risk` as a test oracle: no. It is unpinned; an independent exposure oracle is used instead (section 4.2). | Answered |
| Q-N2 | Is the pin by a network-free local clone (`clone --no-checkout --no-hardlinks` from the lab clone, `checkout --detach`, remote removed, read-only) OK? Or do you prefer `git archive`? Who bumps pins? <br>**Answered by Nuance** (PR #4 review, 2026-10-16): keep 76f71dc, and bump only when a closure module the suite needs, or the month roles, change. "Allowlisted file" means every `PINNED_FILES` entry (section 3.5). The review does not say whether Nuance prefers `git archive` or who bumps pins. <br>**Nuance's PR #2 review answers the rest:** "Keep the network-free clone after 2 and 10" (both fixed: e51b469, 816e832). "Drop 3.5 item 3's git_state reason (11); keep the upstream IN_GIT_CHECKOUT one" (section 3.5). "Lab-Claude bumps in its own PR only to a sha Nuance names on main"; `vendor` now refuses a commit that is not on the research main branch (`commit_not_on_main`; 1d23fdc), because "cat-file -e accepted unmerged and dangling commits". "Nuance reviews every bump; Astra reviews pin and vendor code. Routing is proposed until Yu rules (Q-Y8)." | Answered |
| Q-N3 | **State root and the run marker.** Is `~/betangel-data/suite.noindex` acceptable? Following your A5 answer, the suite will not run at all during your runs. Will your run and ingest wrappers write a marker such as `~/.local/state/lab-runs/ACTIVE`, and wait for `~/.local/state/betangel-suite/run/engine.lock` to be free before touching sources or data? <br>**Answered by Nuance: yes to both** (PR #4 review; mailbox, 2026-10-16 13:41Z).<br>- Root: `~/betangel-data/suite.noindex`, on three conditions (section 3.7): (1) Nuance never uses `~/betangel-data` or `suite.noindex` itself as a data or lab-state root; (2) before Phase 1a, the suite refuses a data root that equals, contains or lies inside `suite.noindex`, `lab-state` or `logs`, or lies inside `incoming/`, comparing by file identity (owed before Phase 1a); (3) the marker half is agreed first. `roots.STATE_ROOT_AGREED` was set True after this answer.<br>- Marker: `~/.local/state/lab-runs/ACTIVE`, on Nuance's terms (section 6.8). Nuance's wrapper creates it with O_EXCL: "Wait at least 60 s for engine.lock, and fail closed if it is still held. Treat a missing lock file as free and any other error as busy". Nuance measured the lock free only after 30.23-30.60 s (PR #4 review, item 15); the engine may hold it for about 35 s after the marker appears. <br>**Nuance's PR #1 review (item 5) adds:** the marker covers every upstream step on real roots, by rule; Nuance adds a marker step to each block of the runbook's section 10.1; and `run/realdata.lock`, which real-data processes hold shared and Nuance's wrapper takes exclusive (section 6.8). <br>**Conditional again since Nuance's PR #2 review** (2026-10-16): "agree the root half after 1, the marker half after 6". Nuance's PR #2 finding 1 is about roots that resolve into `~/betangel-data`; Nuance's finding 6 is the marker protocol, which Nuance merges with item 5 above (section 6.8). That review also moves the flock of Nuance's wrapper from `ACTIVE` to a never-unlinked `lab-runs/LOCK`, held for the whole job. <br>**Root half:** Nuance's PR #2 item 1 is fixed on this branch (62c39c6, 851885a; section 3.7, "Placement"). Its re-check was asked of Nuance on 2026-10-17, not answered. Nuance's PR #2 review adds: "Nuance's wrappers refuse roots in suite.noindex, and duplicate roots, by identity"; the suite's own duplicate check is owed before Phase 1a (section 5.2). <br>**Marker half:** in Nuance's PR #2 item 6 and PR #1 item 5 Nuance asked for a separate lock (that it is never unlinked is lab-Claude's design, section 6.8), `LOCK_SH` with a re-check, checks between members, a renamed catalogue, and a wrapper `LOCK_EX`: "The wrapper waits 60 s+ for LOCK_EX, failing closed". It is built on this branch (596d052, 18de53e, fbbc0c3; section 6.8). Its re-check was asked of Nuance on 2026-10-17, not answered, and Nuance's agreement of the marker half is still owed. Whether `test`, `uisnap` and `vendor` take the lock was also asked of Nuance on 2026-10-17, not answered. | Phase 0 (root half after Nuance's PR #2 item 1, marker half after item 6) |
| Q-N4 | **PRO ingest.** When will you ingest and index it (a date), and what is the final data root (`historic-pro`?)? Is it one archive sha, with index v1 built as for BASIC? A header listing shows 12,208 market files at depth 6, all PRO, including 8 in 2016-May (in no contract split). Is there anything in the index the picker should surface? <br>**Answered by Nuance** (PR #1 review, 2026-10-16):<br>- No date. The ingest comes after the runbook's section 10.1 releases the TAR, under the run marker, and Yu is told.<br>- A separate root, `~/betangel-data/historic-pro`, with one archive sha and the stock index built at code equal to 76f71dc (the BASIC index was built at da44d71).<br>- "12,200 = 12,200" is a match of counts, not of markets (section 2.4).<br>- For the picker: `files[].status` and `complete_before_pt` (section 5.3).<br>- Close Q-Y16 (done). | Answered |
| Q-N5 | **Paper semantics.** Is direct `PaperExchange` use with a suite `OrderJournal(path, mode="paper", clock=SimClock)` fine, given Yu's R-1? Intent source `paper_replay` with `customer_strategy_ref` `suite-click` (and `suite-test` in synthetic tests), with click provenance in `note` events, until U-9? Is withdrawing a pending order as SUBMITTING → REFUSED (`operator_withdrawn_before_activation`) acceptable? <br>**Answered by Nuance: yes** (PR #1 review, 2026-10-16), through an `rx.py` wrapper (paper mode, `SimClock`), with `suite-click` refs; journals stay under the suite root. On pending orders, in Nuance's words: "The 500 ms models an order in flight and step shows the activation book, so in live-parity Esc on a pending order activates then cancels; withdrawal only for void and badged exploration; readers use the folded error_code." Section 7.6 records what this changes. | Answered |
| Q-N6 | **Quiet-market staleness.** Paper V10 and `_activation_refusal` measure age from the market's last change. Real data shows it is rare near the off. Do you want U-8 at all? (Low priority; the relaxation mode is cut.) <br>**Answered by Nuance: not now** (PR #1 review, 2026-10-16). U-8 stays parked. Split stale refusals by time to the off, and revisit if they show in T-10 to the off (from T-30, 13 of 39 markets had gaps over 10 s; section 7.5). | Answered |
| Q-N7 | **High-water seeding.** Is it acceptable to rebuild `PaperExchange` with a suite-built `state` whose `traded_hwm` is raised to the raw running maximum up to the replay time (conservative, no look-ahead)? Or would you rather publish U-6? <br>**Answered by Nuance: accepted** (PR #1 review, 2026-10-16), with a fresh exchange per attempt (Nuance's probe) and finite trd values only; the test is in the 1b exit (section 7.4). | Answered |
| Q-N8 | Is `config.validate_config` under `StatePaths(home=..., root_override=...)` with FORBID_NETWORK (the test-harness override) an acceptable way to validate the suite's paper config? <br>**Answered by Nuance: yes** (PR #1 review, 2026-10-16), if the suite root is agreed and exists first (else `subprocess_refused`), and the object feeds only `validate_config`: its `kill_engaged()` is a false all-clear (section 3.8). | Answered |
| Q-N9 | **SP display (R-5).** Do you confirm a suite-side, display-only parser needs no repo ruling? Do you plan U-2, including whether SP non-finites should invalidate the whole book? <br>**Answered by Nuance: confirmed** on the terms in section 6.6 (Nuance's PR #1 review, item 11: the tap resets at each image; `spb` and `spl` are deltas, cleared while not OPEN; `bsp` only within [1.01, 1000]). U-2 waits for the M-PRO counts. | Answered |
| Q-N10 | **Rule 4.** Will you take U-1? Until then, is the "indicative, exact-case" figure acceptable? <br>**Answered by Nuance:** U-1 not now; it needs a fact row and per-fill pts (PR #1 review, 2026-10-16). Nuance's item 11 sets the indicative figure's cut-off, label and exclusion from totals (section 7.9). | Answered |
| Q-N11 | **Viewed-markets ledger.** Which fields and format do you want, so markets opened in the suite reconcile with your trial ledger? Agents never read the ledger; reconciliation is by code over salted hashes, printing match counts only. Does human practice on the engineering year matter to P0 or P1? <br>**Answered by Nuance** (PR #1 review, 2026-10-16): month level. The fields are a keyed hash, plan, month, role, opened_by, furthest phase, attempts and ruling id. Counts come from `ledger-summary`, with no hash matching: the trial ledger holds no market ids (trial_ledger.py:96). Human practice on the engineering year has no effect on P0 or P1. A research month that is opened becomes inspected (contract.py:39). Sections 5.3 and 5.5 record this. | Answered |
| Q-N12 | **Review routing.** Do you agree the routing in section 3.9 (Astra for guard, rx, errors, release, run marker, api, boundaries, scanner and pins; you for data and paper; Yu alone for UI-only PRs)? Should lab-originated review requests arrive as a lab-journal coordination task plus a mailbox note? <br>**Answered by Nuance: "agree once amended"** (PR #4 review, 2026-10-16). Nuance asked that "every reviewer whose rows the diff touches accepts it at a named head sha", that "engine.py and the roots are reviewed jointly", and that Nuance's row gain `synthetic.py`, `tests/fixtures/`, `tools/export_ticks.py`, `ui/ticks.json` and `replay/`. Section 3.9 and AGENTS.md now say exactly that. <br>**Nuance's PR #1 review (item 9) amends Nuance's view:** a governance row for rule documents (AGENTS.md, this document, `docs/data-handling.md`, `docs/proposals/`, `tools/stage/`) to Nuance and Astra at a named SHA, which Yu rules on (section 3.9). Asked of Yu on 2026-10-17, not answered. <br>**Nuance's PR #2 review adds** (Nuance's Q-N12 additions): "config.py, data-handling.md and tests/__init__.py to Astra and Nuance; a fail-closed row for unnamed files; changes to AGENTS.md's rules or routing also need Yu." The first is now a row in section 3.9 and AGENTS.md; it only adds reviewers. The second names no reviewer: section 3.9 and AGENTS.md send unnamed files to Astra and Nuance jointly, which is lab-Claude's reading, and whether the row should follow Nuance's PR #1 item 9 ("uncovered diffs go to Yu") instead was asked of Nuance on 2026-10-17, not answered. The third is part of the governance row, asked of Yu on 2026-10-17, not answered. Nuance also sends "Every touched reviewer accepts the same head SHA" to Yu as a Q-Y8 clarification. <br>**Still open.** Adding `cli.py`, uisnap and `tools/stage/` to Astra's row is lab-Claude's proposal, from Phase 0c's review plan, not Nuance's request. It only adds a reviewer; Yu rules on it with you (Q-Y8), and Yu can override it. The review does not answer the second part (how review requests arrive). Nuance asked that Yu be asked to clarify Q-Y8 so that tests must pass on 3.13 and 3.11 at the accepted SHA ("Ask Yu to clarify Q-Y8 so that tests must pass on 3.13 and 3.11 at that sha"). Lab-Claude asked Yu on 2026-10-16, and Yu answered "Its all good :) Merge when sensible" (section 2.2.1). | Answered in part |
| Q-N13 | **The Air later.** Does the Air have the Command Line Tools and Swift? Which Python is there? Will you host the Air-side package (L1/L2) in a separate repo, or in betangel-research, never cloned on the lab? <br>**Answered by Nuance** (PR #1 review, 2026-10-16):<br>- The Air: M2, the Command Line Tools 26.4, Swift 6.3.0, and python3.13 3.13.15 (installed after Nuance's PR #4 review).<br>- The Air-side package goes in a separate repo under Yu's account, never betangel-research, which is cloned on the lab (section 3.1).<br>- L1 is built on the Air from the merge SHA. The lab-build fallback is dropped (section 12). | Answered |
| Q-N14 | **Tests during your runs** (from the Phase 0c build). Under adaptation E (AGENTS.md), `bin/suite test` (the fast tier) ran while the run marker existed. Since Phase 0c it starts more synthetic engine children (`serve`, `open`, `ssh-session`) in temporary HOMEs, whose marker checks read the temporary HOME's marker path. Rule 7 of section 3.9 says no suite engine runs while the marker exists. Is a fast-tier run during your run acceptable, or should `bin/suite test` refuse then, as `test --heavy`, `uisnap` and `release` already do?<br>**Answered by Nuance: no** (mailbox, 2026-10-16 13:41Z; PR #4 review, item 14): "Please make the fast tier refuse while the marker exists too; stop stays exempt". `bin/suite test` now refuses both tiers, on both interpreters, while the marker exists; a run already going stops before its next test, or its next module, once the marker appears; and the test helpers check the real marker before each engine they start (section 6.8). Your PR #1 review added: "test and vendor refuse under the marker; stop stays exempt". `vendor` now refuses too. Nuance's PR #2 review answers the same way: "No. Drop `test` from NO_RUN_MARKER_CHECK; from #4 the fast tier starts ~20 temp-HOME engines blind to the real marker. Check it per module in _run_workers.assign()." The parallel test runner does (section 6.8). | Answered |
| Q-N15 | **Rule 1 reword (Q-Y19).** Yu chose option D, which rewords rule 1's network clause so that it does not cover the two R-2 Air files, `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh` (sections 2.2.1 and 3.9). Do you agree with the wording? This row also asked whether a rule 10 proposal file is needed. Yu answered that on 2026-10-16: "yes to formal proposal". That file is `docs/proposals/002-air-viewer-files.md`.<br>Your first view of the wording (mailbox, 2026-10-16 13:41Z, item 5) is quoted in proposal 002, section 2.4.<br>**Answered by Nuance** (PR #1 review, 2026-10-16, at the stack tip, which the review names as c051b2d): "faithful; agree, as "the only exception to this rule"". c051b2d's rule 1 text is the current one. Lab-Claude's reading: the phrase frames the two files as an exception to rule 1, while option D's text calls the reword "a clarification rather than a widening" (Q-Y19). Adopting the phrase would change rule 1's text, which needs Astra's review and Yu's written approval, so rule 1 is not changed for it; lab-Claude takes it up in proposal 002's review (proposal 002, sections 2.4 and 10).<br>**Still open:** your review of proposal 002 as a whole (proposal 002, section 10), and your acceptance of PR #5's changes to `roots.py` and `engine.py`, which you and Astra review jointly (proposal 002, section 9, step 1). Astra's re-review of PR #5 at d9b129e says: "**Q-Y19/Q-N15:** I accept the narrow wording as implementing Yu's D ruling and do not reopen the resolved P1." That covers d9b129e's wording: c051b2d, the next commit, changed rule 1's text (proposal 002, section 4.4), so Astra still reviews the current wording with proposal 002 itself. Then Yu is asked for written approval. | The wording: answered by Nuance at c051b2d. Proposal 002's review: before PR #5 merges (proposal 002, section 9) |

### 15.3 For Astra

**Phase 0 review:** Q-A1 and Q-A2, alongside the review routed in section 3.9. Both are answered; Q-A1 leaves the ruling to Yu (Q-Y17).

| ID | Question | Needed in |
|---|---|---|
| Q-A1 | **Read-only tab and STOP** (with Q-Y17). The code follows section 9.2 item 8: `claim_control` is the only command a read-only tab may send, so STOP answers 409 `not_controller` there. Section 8.2 item 8 says STOP is always reachable by key. Would letting a read-only tab send `stop` be acceptable for the API's authorisation rules? Yu rules after your view.<br>**Answered by Astra** (re-review of PR #5 at d9b129e): "a narrow authenticated, idempotent safety-stop exception is acceptable in principle. It should grant no other controller powers and retain the existing request checks. Yu decides". Astra also wrote that "the current controller-only behavior is intentional, not a new finding". The ruling is Yu's (Q-Y17, open). | Answered (Yu rules on Q-Y17) |
| Q-A2 | **The scanner's article-number exemption.** `tools/hygiene_scan.py` exempted a 7- or 8-digit help-centre article number from the event-id rule, only in an https `/articles/<n>` or `/<locale>/articles/<n>` URL on four Claude and Anthropic hosts. Phase 0c narrowed it to that, but no file in the tree used it. Keep it as it is, or drop it until something needs it?<br>**Answered by Astra** (re-review of PR #5 at d9b129e): "I prefer dropping it until a real documentation need exists." It is dropped. The scanner exempts no URL: the event-id rule treats a digit run inside a link like one anywhere else, and docs/data-handling.md says so. Bringing one back is a scanner change, which Astra reviews. | Answered |

---

## 16. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Review capacity.** Each of Nuance's tasks needs an Astra round (c2b3b3 and c2b3b4, which Nuance was finishing first, are merged). Lab-Claude carries other workstreams. | Elapsed time set by review latency, not coding. | Lab-done and review-accepted exits; stacked branches; one Phase 0 packet; routing proposed up front; UI-only PRs on Yu's acceptance (proposed; section 2.2.1). |
| **PRO ingest timing.** It has no date yet (Q-N4). | Real-data milestones slip. | The synthetic UI is accepted without PRO; M-PRO is its own milestone; Q-N4 is answered and Q-Y16 closed. |
| paper-v1 is deliberately pessimistic: half of displayed size, no credit for cancellations ahead, unknown queues never fill. Practice may teach that resting orders rarely fill. | Skills and expectations are miscalibrated. | Verbatim assumptions, the queue tracker, fill-quality debrief, the R-7 choice, U-7. |
| About half of races have a non-runner, so there is no official P&L. | Frustration, and pressure for ad hoc fixes. | The indicative figure (section 7.9), the library filter, U-1. |
| 2015-16 liquidity and behaviour may not transfer to 2026. Replaying a race teaches its result. | False confidence. | "Not execution evidence" labels, attempt counter, forward-only sessions, the spoiler-free picker. More recent PRO months cost £230 each and touch research and holdout rules (Nuance and Astra). |
| Exact mode on big fields lags near the off (about 8x at 44 runners; about 3x in the busiest second). | Slower than requested speed. | Labelled effective speed; prefetch never during exact mode; open budgets by percentile. |
| 8 GB memory pressure shared with Nuance's work and two Claude sessions. | Swapping, interference. | 600 MB target, 1 and 1.5 GB caps, an LRU of 2, `run_paper_replay` banned on real data, nice, no engine during runs, heavy tests opt-in. |
| Upstream drift: the repo moves several times a day; private behaviours are mirrored. | Breakage on pin bumps. | Pin with per-file hashes, contract and parity tests, reviewed bumps, U-3..U-6 to retire the mirrors. |
| R-1, R-6 or R-7 is unresolved, or resolved against. | Phase 1b is blocked or reshaped. | Ask in the Phase 0 packet. The fallback (a gateway with an overridden root) would import credential-bearing modules, so I do not recommend it; it would need restating I-1. |
| Licensed-data leakage through screenshots, model context, error text, Collab, fixtures, browser history, Spotlight, crash reports or exports. | Licence breach. | Agent-conduct rule, error mapping, hygiene scanner, synthetic-only fixtures and uisnap screenshots, Private window, `.noindex`, Q-Y14/Q-Y15, exports under `~/betangel-data`. |
| A same-uid agent uses the UI as if it were Yu. | Paper journals with false provenance. | Single-use codes, in-memory token, SSH-side refusals, the conduct rule; I-8 stated honestly as a code-path property. |
| Lab-served JS in Yu's Air browser is buggy or tampered with. | A fake login prompt; credentials typed toward the lab; blind requests to other Air loopback services. | No credential fields ever; Private window; reviewed release copies only; no suite listeners on the Air, and a netstat check of the Air's loopback listeners before R-2; L1's tested deny-all content rule (section 8.6). |
| Localhost attack surface regresses. | CSRF or rebinding against the paper API. | Security tests on every PR. No live endpoint exists to abuse. The SSH-stdio shell before any live click. |
| The viewer key's residual capabilities are misjudged. | A least-privilege gap on a key Yu adds. | The sshd drop-in (no `-R`, no streamlocal); the Air-side self-test; the forced command runs a release copy; Yu can remove the line at any time. |
| An Air disconnect (lid closed, Wi-Fi blip) during a race. | A spent race or a locked-out session. | Pause unless watched; heartbeat; grace and takeover; `ClientAliveInterval` in the drop-in. A silent disconnect is bounded by about 3 min until the 5 s `not_watched` pause lands, before 1b (section 8.6). |
| Lab-Claude cannot see the UI. | Late UI bugs and round trips with Yu. | uisnap from Phase 0; JS logic tests; problem reports and `diagnose` for real-data issues. |
| Real-data-only bugs that agents cannot see. | Slow fixes. | Problem reports (codes only), `diagnose` with code-only checks, Yu describing the shape (real values are not available pending Q-Y9; section 8.7), a generator sized like real markets. |
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
5. **Audit hook and git.** The hook allows the exact `git -C <dir> rev-parse --is-inside-work-tree` argv during a startup phase, for `validate_config` and `StatePaths` (paths.py:149, :158; config.py:224-236), and is sealed after startup.
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
  - Pending orders are withdrawn as SUBMITTING → REFUSED.
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

**Phase 0b and 0c sync (2026-10-15).** The text was brought into line with the code on branch phase0/viewing. It describes what the code does. No policy changed, with one exception: section 3.9 rule 6 (and AGENTS.md) now says how `bin/suite test` exercises the commands agents never run.

- **Routing (3.9, 10).** The Astra list now matches AGENTS.md's table, which already named `release.py`, `runmarker.py` and the launcher. The routing itself did not change. Phase 0c's review plan also sends uisnap, the staged viewer scripts, `cli.py` and `roots.py` to Astra; whether the table names them is added to Q-N12, not decided here.
- **Layout and launcher (3.4, 3.6).** `engine.py` and `synthetic.py` in place of `replay/`; `api/lifetime.py` and `api/sshsession.py`; `uisnap.py`; `tools/export_ticks.py` and `ui/ticks.json`; the keymap in `ui/app.js`; the staged files and `tools/uisnap/`. Phase 0's three launcher differences, the full `env -i` list, the test runner's worker interpreters, and `ssh-session --port` for tests only.
- **State and config (3.7, 3.8).** `uisnap/build` and `uisnap/out`; only `engine.lock` and `control.sock` in `run/`; owner-only release copies; `max_session_s`; the accepted ranges.
- **Frames (6.5).** The Phase 0b subset; every number is an integer, and the market and runners carry ids and names.
- **Viewing (8.6).** How a release is made and checked (`wrong_owner` for the owner check); `open --print-url` and the lab-screen lines; every staged file; the seven hardening lines of the Host block (tests/test_stage.py pins the snippet to it) and what the self-test's preflight checks; the ssh window's stdout lines and its code-only stderr lines; pause unless watched as built (hosting and attached `ssh-session`, signals, `open` takeovers never abandoned and how they do end, `max_session_s` for every engine, the takeover note deferred to Phase 1b); nine self-test probes over five logins; the same-uid forced command, release copy, shell startup files and `authorized_keys` line, with only the drop-in beyond a same-uid process (also 9.4). `tools/stage/README.md` ("Daily use") follows the same text.
- **API (9.1, 9.2).** The four viewer commands on the control socket and `LOCAL_PEERCRED`; `claim_control` as the one command a read-only tab may send.
- **Invariants (10).** `permit_unix_connect` in I-3; I-5 per guard mode; I-18 and I-19 as tested.
- **Testing (11, 12).** The measured tiers; the heavy tier's run-marker refusal; the `state_root_changed` check (entries only, not contents); pre-commit runs the scanner only; the node command; uisnap as built (the backing scale, the default output directory and `--out`); the Phase 0 status.
- **Open questions (15).** Q-Y17 and Q-A1 (a read-only tab cannot STOP: 8.2 item 8 against 9.2 item 8), Q-Y18 (who makes release copies), Q-N14 (the fast tier during a run marker), Q-A2 (the scanner's article-number exemption), and an addition to Q-N12 (the paths Phase 0c's review plan sends to Astra that the table does not name).

## Appendix C. Nuance's PR #1 review (2026-10-16)

Nuance reviewed this document at daf9c64 from the upstream and data side: one conditional P1, nine P2s and a list of P3s. Yu's rulings are not reopened. Changes to files that the design branch does not have are made on the branches that do: AGENTS.md and `docs/data-handling.md` on phase0/foundation (67524f4, 632dbda), and proposal 002 and the code on the later branches.

- **1 (conditional P1).** The ladder-type condition: sections 0, 7.1, 7.3, 11 and 12, and U-10.
- **2.** Real values in a model context are not available pending Q-Y9: rule 5, section 8.7, Q-Y9.
- **3.** Rule 5 covers all of `~/betangel-data` and the install salt; deny rules for lab-Claude's file tools, which Yu approved on 2026-10-16: rule 5, sections 9.2 and 9.4, Q-Y9.
- **4.** Headless real-data commands run only reviewed code: sections 8.6, 10 (I-16, I-18) and 12.
- **5.** The marker's scope by rule, and `run/realdata.lock`: section 2.3, rule 7, sections 6.8 and 10 (I-17), Q-N3.
- **6.** Screen capture on the Air: rule 5, sections 8.6 and 9.4, Q-Y10, and the screenshot row of `docs/data-handling.md`, which now says "on the lab" and covers the Air separately (applied in lab-Claude's round-4 review).
- **7.** Other Air loopback services: sections 8.6, 9.4, 12 (L1) and 16.
- **8.** The silent-disconnect bound, and the 5 s `not_watched` pause owed before 1b: sections 8.6, 10 (I-19), 12 and 16.
- **9.** The governance row for rule documents, asked of Yu on 2026-10-17, not answered: section 3.9, Q-N12, Q-Y8.
- **10.** Q-Y8 corrected, and R-3 and R-7 marked as stated defaults: sections 2.2.1, 3.9 and 15.1.
- **11 (P3).** The Rule-4 cut-off (7.9); the SP tap's terms (6.6); the trial ledger and inspected months (5.3, 5.5); session ids and end statuses (7.10); partial invariants and the Air viewing gate (0, 12); no data-root read before the root is agreed (5.2); the practice loss limit (7.2); the Air-side repo (3.1); "tick-by-tick" (5.1); the Safari clean-up now (8.6, Q-Y11); `research_months_ruling` (3.8); release by merge SHA, silent codes, the checklist as a log and scanned outbound text (8.6, 9.1, 3.9, 5.6); stale I-14 and c2b3b3/c2b3b4 (0, 2.4, 10, 16, Q-Y16).
- **Questions.** Nuance's answers to Q-N4..Q-N11 and Q-N13 are recorded as Nuance's, and Yu can override them (section 15.2).

## Appendix D. Nuance's PR #2 review (2026-10-16)

Nuance reviewed PR #2 at 93e26e6, the whole PR from Nuance's side, plus an independent pass on the guard and scanner after Astra's fixes: five P2 code defects (1-5), one P2 in design text (6), and P3s (7-22). The fixes are on this branch. Nuance's re-check of each, and Astra's review of the Astra-routed files, are owed at one head SHA; the re-checks of items 1 and 6 were asked of Nuance on 2026-10-17, not answered.

| Item | What | Where it is fixed | Sections |
|---|---|---|---|
| 1 (P2) | Roots that resolve into `~/betangel-data` were trusted | 62c39c6, 851885a | 3.7 "Placement", I-6; the root half of Q-N3 |
| 2 (P2) | `vendor` wrote into the deploy clone through a linked ancestor | e51b469 | 3.5 item 1, I-13 |
| 3 (P2) | Unguarded child processes after `seal()` | 56a2631, 9a8a11b | 3.2, 4.1, I-5 |
| 4 (P2) | `listen()` on an unbound socket binds 0.0.0.0 | 01f6201 | I-4 |
| 5 (P2) | The scanner missed encoded or late binary data | 50fe1b7, 6149d94 | 5.6, I-9. The `encoded_blob` text criterion (decoded text that another rule flags) is lab-Claude's addition beyond the review's fix text. |
| 6 (P2, design text) | The marker protocol covered engines only | 596d052, 18de53e, fbbc0c3; `run/` protected too in 6aeb1d5 | 6.8, I-17, Q-N3. The re-check was asked of Nuance on 2026-10-17, not answered, and Nuance's agreement of the marker half is owed; whether `test`, `uisnap` and `vendor` take the lock was also asked of Nuance on 2026-10-17, not answered. On phase0/http `serve` and `open` take it, and have their I-17 tests, since round 4b (98741d3, 560a284); `ssh-session` takes it on phase0/viewing. The I-17 tests of `ssh-session` (phase0/viewing), `ledger-summary` and the headless commands are owed with their handlers (section 6.8, "Owed"). |
| 7 | Imports were not held to the closure | 923c1de, 08af945 | 3.5 item 4, 4.2, I-13 |
| 8 | Links in deps reached the clone | e4ddc18, 7357273, 0a1c482 | 3.5, 4.1 (`backtest.contract`), I-13 |
| 9 | A falsy rng fell back to `secrets` | ec039db | 4.1, 7.3 |
| 10 | `vendor_argv_ok` ignored the child's environment | 816e832 | 3.5 item 1, I-5. Nuance's note for Astra, that `runner_git_ok` passes `DEVELOPER_DIR`, is not changed yet. |
| 11 | The parity oracle cannot run under the test guard | docs only; the stub is owed before 1b | 3.5 item 3, 4.2 |
| 12 | `research_months_ruling` accepted any id | 3f51ae7 | 3.8, 5.3 |
| 13 | No rule protected the real marker | docs; fbbc0c3 tests that the guard keeps every suite mode out of `lab-runs/` | rule 7 (3.9, AGENTS.md) |
| 14 | The salt was unprotected | docs; lab-Claude's file tools deny it (Q-Y9) | rule 5, 9.2 item 9, AGENTS.md adaptation B, `docs/data-handling.md` |
| 15 | SQLite temp files could leave the roots | 06dba20 | 3.6, I-6 |
| 16 | The ATTACH limit could be raised | 3da0c26 | I-6 |
| 17 | Read-only descriptors changed metadata | 59e2f22 | I-6 |
| 18 | `_ctypes` reached libc without `dlopen` | 886d64b | I-5 |
| 19 | Clean filters bypassed the staged scan | 526efcb | 5.6, I-9. The rule on a `.gitattributes` line that sets a filter is lab-Claude's addition beyond the review's fix text. |
| 20 | Messages and pushed history were unscanned; in Nuance's words "P2 before Phase 1" | 268d02d | 5.6, 9.4, I-9, AGENTS.md "Repository hygiene" |
| 21 | `runner_table` missed tables | ebd1038 | 5.6, I-9 |
| 22 | A FIFO at `config.json` or `install-salt` hung | 53239a3; the pin's reads in e4ddc18 | 3.8, 3.5 item 4 |

Nuance's answers to Q-N2 (section 3.5 and the Q-N2 row) and Q-N14 (section 6.8), and Nuance's additions to Q-N3 (sections 3.7, 5.2, 6.8 and the Q-N3 row) and Q-N12 (section 3.9, AGENTS.md and the Q-N12 row), are recorded as Nuance's, and Yu can override them.

## Appendix E. Lab-Claude's round-4 review (2026-10-17)

Lab-Claude's own review of this branch after the round-4 fixes (lenses on the guard and marker, the vendor tool and scanner, and the documents), and its recheck of those fixes, before Nuance's and Astra's re-checks. A finishing review followed (lenses on the guard, the scanner and the documents; rows marked "Finishing review"). Its guard lens did not finish and reports no findings, so the guard has no finishing review. A recheck of the finishing review's fixes found five more low findings (rows marked "Finishing recheck"); the row on 15.1's status labels is lab-Claude's decision on a question the finishing review's refix left open. A review of the guard's paths, layouts and SQLite parts then wrote a regression-test file and ran it against archive copies of this branch. It found five low findings (rows marked "Guard paths"). Lab-Claude found the variants those rows name while fixing them: the review's prototype fixes left them open. A second recheck, of the finishing recheck's and the guard-paths fixes, found three more low findings (rows marked "Second recheck"). Lab-Claude then decided two questions the guard-paths fix had left open (rows marked "Guard-fix question"). Each finding was checked again before it was fixed; each code fix has a test that fails without it.

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
| The fail-closed routing row was credited to Nuance, who named no reviewer, and clashed with "a diff no row covers goes to Yu" (medium) | 818fb17; asked of Nuance on 2026-10-17, not answered | 2.2.1, 3.9, Q-N12, AGENTS.md |
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

**http, round 4b** (phase0/http, 2026-10-17). phase0/foundation's round-4 fixes were merged into phase0/http at 823c194 (98741d3); that merge changed the tests that renamed `run/` in a guarded child, and added three entries to the I-10 allowlist (section 6.8, "Owed"; the I-10 row). Round 4b then did what phase0/http owed from lab-Claude's round-3 replies and from section 6.8. Each new test failed on a scratch copy of the code it pins, changed to break what the test claims, before the copy was restored.

| Item | Fix | Sections |
|---|---|---|
| `open` and `serve` while an engine is still starting: 8.6 item 1 said only that `open` attaches, and lab-Claude's first reply on #4 said `open` refused with `engine_running`. Astra's re-review of #4 found `control_unavailable`, and judged that `open` and `ssh-session` not waiting is "acceptable as a safe usability limitation" (the first version of this row said Astra accepted it for `open` and `serve`; round 4b's review) | eba5b1b: the text, and two tests (one `attach` request and no second; the wait for a reply on a bound socket, up to 5 s) | 8.6 item 1 |
| The hard-linked control socket was not written down (Astra's re-review of #4) | 9f66d00: in Astra's terms; no code change | I-3, `guard.py`'s I-3 entry |
| The check-then-use limit of `engine_argv_ok` and `runner_git_ok`, and of `vendor_argv_ok`, was not written down (lab-Claude's reading, from its round-3 reply to Astra) | 9f66d00 | I-5, `guard.py` |
| The wrapper's waits were restated ("at least 60 s", "60 s or more") instead of quoted. Nuance's 13:41Z wording for `engine.lock` differs; which one Nuance wants was asked of Nuance on 2026-10-16, not answered | 9f66d00: quoted from Nuance's PR #4 and PR #2 reviews | 6.8, I-17, Q-N3, AGENTS.md E |
| The I-10 rule missed short spellings, and the I-10 row and 4.5 claimed more than it did (lab-Claude's round-3 review of #4, low): `from os import sys`, `importlib.import_module('sys').modules`, `__import__('sys').modules`, `sys.modules['sys'].modules`, `sys.modules['betangel_suite.rx']._archive`, `sys.modules['builtins'].exec`, `__import__('builtins').exec`, `engine.rx._archive`, `from .engine import rx` | 6feff7c: each refused, with lab-Claude's variants (`s = sys; s.modules`, `getattr(x, "modules")`, `getattr(x, "rx")`, `inspect.getmodule`); 28 new planted cases, all failing with the old checker | 4.5, I-10 |
| `CoverageTests` counted only `rx.<namespace>.<name>`, so a name reached through `from .rx import ticks` or an alias escaped it (lab-Claude's round-3 review of #4, low) | 6feff7c: it counts every spelling, rx reached through another module included | 4.5 |
| A keyless synthetic variant (Nuance's PR #1 review, item 1(d)) | f23ba3f: `no_ladder_definition`. Tests show the book's `price_ladder_type` None, `validate_place` refusing every paper click with V9 `ladder_not_classic`, and the engine's frame unchanged. V9 and the CLASSIC default are not changed (Yu's under D-5) | 7.1 item 4, 11, 11.1 |
| The realdata lock's I-17 tests for `serve` and `open` (section 6.8, "Owed") | 560a284: tests only; the wiring came with the merge (98741d3) | 6.8, 8.6 item 1, I-17, AGENTS.md E |

One commit message to correct, since commits are not rewritten: f23ba3f says `validate_place` refuses "each of 30 clicks (both sides, every runner, three times)". The test checks 36: six runners, both sides, at three times.

**viewing, round 4b** (phase0/viewing, 2026-10-17). phase0/http at d00436e, which holds phase0/foundation's round-4 fixes, was merged into phase0/viewing (b837d38). That merge did what section 6.8, "Owed", asked of this branch for the merge itself: `cli.NO_TMPDIR` is `("stop", "vendor", "release")` with the `run_lock_not_held` check inside its branch, `ssh-session` holds `run/realdata.lock` for its life, and the tests that renamed `run/` in a guarded child changed. It also added `run/realdata.lock` to `cli.ENGINE_ENTRIES`, so the test run's state-root check explains it. Round 4b then did what phase0/viewing owed from lab-Claude's round-3 replies, from section 6.8 and from Nuance's PR #1 review. Each code fix has a test that failed on a scratch copy with only that fix taken out, before the copy was restored.

| Item | Fix | Sections |
|---|---|---|
| The flaky `SignalTests` run ("not created: attach-ready" after 30 s, under load), whose cause round 3 had not found, was a race in the writer helper. Two commands started together in a new HOME both make the suite root's `tmp/`. When it appeared between `roots._make_dir`'s `lstat` and its path guard, the guard refused `path_denied:already_exists`, and the second command died at once. Under full `-j 2` load, 12 of 60 runs failed so before the fix and 0 of 60 after (lab-Claude's measurement) | 68a4b46: a directory made meanwhile, before the guard or between the guard and `mkdir`, is judged as an existing entry; a link put there is still refused. The test now reports a child that exits early. `roots.py` is the same on phase0/foundation and phase0/http, so the race is there too; moving the fix down is lab-Claude's open question | 3.7 |
| An attached `ssh-session` noticed the engine's end only at its next heartbeat, so after the marker appeared it could hold `realdata.lock` for about 50 s (45.55 s in the test), past the 35 s bound. Lab-Claude's decision, sent to Nuance on 2026-10-17, was a check on every poll (section 6.8, "Owed") | e9729a6: it checks the marker before every poll and leaves at once (`ended reason=run_marker`, exit 2), under 10 s in the test; docs 88570e8 | 6.8, 8.6 item 2, I-17, AGENTS.md E |
| `open`'s attach path handed on a URL for an engine that was freezing for a run announced during the takeover | e9729a6: one more marker check after the takeover's reply; it refuses and hands on no URL; docs 88570e8 | 6.8, 8.6 item 1, I-17 |
| The I-17 tests for `ssh-session` and `open`'s attach path (section 6.8, "Owed"), and one for `test` and `uisnap` not taking the lock | e9729a6: `RealDataLockTests` in `tests/test_session_process.py` (attached, hosting, `run_lock_busy` before any takeover, the marker under the lock), the attach-path test in `tests/test_engine_process.py`, `run_attached` in `tests/test_session_lifetime.py`, and `tests/test_runmarker.py`; docs 88570e8 | 6.8, I-17, AGENTS.md E |
| The worker's stop in the middle of a module had no test, though AGENTS.md F and section 6.8 described it as working (lab-Claude's round-3 reply to Astra) | 0e2d289, and fa1d529 for 3.11: tests only. A mutation check stands in for a revert: with the worker's plain result class, the test fails; docs 88570e8 | 6.8, AGENTS.md F |
| `release` took a tag (Nuance's PR #1 review, P3: "`release` takes the merge SHA") | cdda336: a full lowercase 40- or 64-hex commit id only; `<id>^{commit}` must give the id itself; that commit's tree is copied, never `HEAD` or the working tree; `app/<sha12>`; `RELEASE.json` format 2 with no tag; `release_commit_invalid` and `release_commit_unknown` replace `release_tag_invalid` and `release_tag_unknown`; docs 9b044c9 | 3.6, 3.7, 8.6, I-5, Q-Y18, AGENTS.md D, `tools/stage/README.md` |
| Replace refs and grafts in the checkout reached `release`'s git: a `refs/replace/` entry made `release <c1>` install c2's tree under c1's id, and a graft let a commit main does not contain pass the main check. This was the viewing merge's open question, the class phase0/foundation fixed for `vendor` (7dc20d7) | 972f555: `guard.RELEASE_GIT_ENV` is the exact `GIT_*` set, with `GIT_NO_REPLACE_OBJECTS=1` and `GIT_GRAFT_FILE=/dev/null`; docs 9b044c9 | 8.6, I-5 |
| `new_code` and `viewer_code` mint silent codes (Nuance's PR #1 review, P3). Rule 6 did not name `attach_viewer` and `viewer_code` | No code change: Nuance's review asks for text. b837d38 names both in rule 6, 9.1 and 9.4; 0a3cc26 says it in `api/control.py` and `api/routes.py`; 065c490 gives the reasons, and an unguessable viewer token is lab-Claude's open question | 3.9 rule 6, 9.1, 9.4, AGENTS.md rule 6 |
| Outbound PR text is scanned with `hygiene_scan.py` (Nuance's PR #1 review, P3) | No code change: no tool in this repo writes or posts PR text, so the scan stays a manual step (AGENTS.md, "Repository hygiene"); 065c490 | 5.6 |
| The checklist file is a log, not acceptance (Nuance's PR #1 review, P3). Proposal 002 section 9 still took Yu's approval "in an acceptance checklist file Yu edits" | 2bf17fb (proposal 002), 065c490 (8.7, 11) | 3.9, 8.7, 11, proposal 002 section 9 |
| Astra's acceptance of the rule 1 wording was quoted without saying that c051b2d, the next commit, changed that wording, and proposal 002's Base line left c051b2d out (lab-Claude's round-3 reply to Astra) | 2bf17fb: the acceptance covers d9b129e's wording; Astra's review of the current wording is asked | Q-Y19, Q-N15, proposal 002 sections 3, 4.4, 9 and 10 |
| Nuance's answer to Q-N15 (PR #1 review, at c051b2d) was not recorded | 2bf17fb: recorded as Nuance's words; that the phrase frames the files as an exception, where D's text says "a clarification rather than a widening", is lab-Claude's reading, taken up in proposal 002's review | Q-N15, 15.2, proposal 002 sections 2.4 and 10 |
| The 15.2 intro counted Q-N12 as answered (lab-Claude's round-3 reply to Astra) | b837d38; 2bf17fb names what is still asked: the governance row, the fail-closed row's reviewer, and how review requests arrive | 15.2 |
| The `air_config_*` row of the stage README's "Common refusals" gave one diagnosis where the self-test's hint gives two (lab-Claude's round-3 reply to Astra) | 065c490: another block adds or sets the value, or the lab-suite block itself lacks a line or has a wrong one | `tools/stage/README.md` |
| Nuance's PR #1 items 7 and 8 were in 8.6, 9.4 and 16 (from phase0/foundation, merged in b837d38) but not in the stage README Yu follows | 065c490: the netstat check of the Air's loopback listeners before the first viewing; close the tab and the ssh window rather than only the lid, since a silent disconnect pauses only within about 3 min | `tools/stage/README.md` |

**http, round 4b's review** (phase0/http, 2026-10-17). Lab-Claude reviewed round 4b on both branches (adb7c63..d00436e here) for the merges, the real-data lock and the docs; "round 4b's review" in the text means that review. It found what follows on this branch. Each behaviour fix has a test that failed on a scratch copy with only that fix taken out, before the copy was restored.

| Item | Fix | Sections |
|---|---|---|
| The I-10 allowance the merge added for `_PinnedLoader`'s base, `(pin.py, None, "computed_import")`, matched every module-level computed import in `pin.py`: a module-level `exec` planted there passed, and the same line in `roots.py` failed | 5148bca: a class statement's bases are reported under the class's name, and the entry is `(pin.py, "_PinnedLoader", "computed_import")`; a module-level or class-body `exec` in a `pin.py`-shaped source is refused | I-10 |
| The I-10 rule refused `getattr(x, "rx")` and `x["rx"]` (and `"modules"`) but not their siblings, so its docstring, the I-10 row and 4.5 claimed more than it did: `vars(engine).get('rx')._archive`, `globals().get('rx')`, `os.__dict__.get('sys').__dict__.get('modules')`, `sys.__getattribute__('modules')`, `object.__getattribute__(sys, 'modules')` and `operator.attrgetter('rx._archive')` gave no finding. Lab-Claude found `pkgutil.resolve_name(...)` too | 1d55ae6: the strings `"rx"`, `"modules"`, `"sys"` and `"builtins"` are refused outside docstrings, and so is an `attrgetter` path with such a part; `resolve_name` is a loader name; 18 new planted cases, each failing with the old checker. The docstring, I-10 and 4.5 say what the rule still does not read | 4.5, I-10 |
| 6.8, `runmarker.py` and a `cli.py` comment said the guard refuses data-root reads in `test`, `uisnap` and `vendor` modes. It judges writes only: a probe read a file under a temporary HOME's `betangel-data` in each of those modes | 9333420: text only. It names what keeps their reads off data roots, and the residual: a test that read a real data root would be neither refused nor holding the lock | 6.8, `runmarker.py`, `cli.py` |
| `runmarker.py` still paraphrased the wrapper's wait ("waiting 60 s or more") | 9333420: Nuance's PR #2 words | `runmarker.py` |
| Text that round 4b made stale: 6.8 described the attached `ssh-session`'s per-poll check as future work, and Appendix D row 6 and AGENTS.md E called the wiring owed on both branches; round 4b also added two whitespace-only lines | afe426f | 6.8, Appendix D row 6, AGENTS.md E |
| `open`'s attach path on this branch hands on a URL for an engine that is freezing for a run announced during the takeover. e9729a6 closed that on phase0/viewing only, and no text here said so | afe426f: recorded in 6.8; moving the check down is lab-Claude's open question | 6.8 |
| Attribution: 8.6 item 1 and the eba5b1b row above credited Astra with accepting that `serve` and `open` do not wait, and 9.1 credited lab-Claude's "nothing is printed to Yu or opened" to Nuance | afe426f: Astra's and Nuance's own words, quoted | 8.6 item 1, 9.1 |
| Nuance's count (mailbox, 2026-10-17 08:41Z: `priceLadderDefinition` in 0 of 12,208 indexed BASIC engineering-year markets) was in no round-4b report, and 7.1 item 4 still said "If the key is present, nothing else is left" | afe426f: item 4 records the count in Nuance's words; the M-PRO count is still owed | 7.1 item 4 |

**Left, owed on the branches below this one first, then merged up:**
- design/mvp-draft-0.2: sections 0 and 1.2, 7.1 items 1-3, the Phase 1b exit (section 12), U-10 (section 14) and Appendix C item 1 still read the BASIC count as pending. Nuance's note: "Section 0, 1.2, 14 and the 1b exit can drop "conditional on the count" for BASIC". 9.1's `new_code` line is design text too.
- phase0/foundation: 6.8's "Who does not take it" and `runmarker.py`'s reason (the guard and reads), and the 9.1 line from design.
