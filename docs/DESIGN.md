# betangel-suite: design (MVP: offline replay and paper trading)

| | |
|---|---|
| Status | Draft 0.2, for review (review round 2 applied; see Appendix B). Yu's Phase 0 rulings recorded 2026-10-15, and the Q-Y19 ruling 2026-10-16 (section 2.2.1). Synced with the built Phase 0b and 0c code (branch phase0/viewing) on 2026-10-15; see the end of Appendix B. |
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
- **Viewing.** Yu can use the lab's own screen. From the Air, Yu uses a forced-command SSH tunnel key plus an sshd drop-in that Yu installs (R-2). This is offered from Phase 0, so Yu can look from the Air in week 1-2.
- **Upstream code.** betangel-research is reused from a read-only, network-free local clone pinned at 76f71dc. Every file is hash-checked, and imports go through one facade module. The engine imports 25 upstream modules (verified 2026-10-15). None of them is gateway, transport, auth, credentials, esa, api, recorder, killswitch, arming, presence, reconcile, risk or capability.
- **Book state.** `book.MarketBookCache` rebuilds the book. A small yield tracker mirrors `book.snapshots_from_recording`, so the suite can produce exactly the snapshot the oracle would see at any moment without taking a snapshot of every message.
- **Paper fills.** These come from `paper.PaperExchange`, driven directly rather than through the gateway, with a suite-owned `journal.OrderJournal(path, mode="paper", clock=<SimClock>)` per session.
  - While any paper order is pending or open, the suite steps the exchange on every message that changes the market, as the oracle does. If the CPU cannot keep up, the replay clock lags; it never skips messages.
  - Parity with the oracle is tested on synthetic fixtures under a stated contract (section 7.4).
- **Coexistence.** No engine runs during Nuance's announced runs or ingests. An agreed marker file outside `~/betangel-data` stops it (section 6.8).
- **No policy amendment needed.** The MVP needs no amendment to trading policy and no change to betangel-research.
  - It does need a one-page **Phase 0 packet** of rulings from Yu (R-1..R-7, section 2.2).
  - The packet includes the three points Nuance said need Yu's ruling before code (mailbox, 2026-10-15 12:30Z): driving `PaperExchange` directly (R-1), SP display (R-5), and rule-generated paper orders (R-6; the MVP has none).
- **Plan.** Phase 0 (scaffold and viewing), Phase 1a (replay ladder), Phase 1b (paper) and Phase 1c (polish and sign-off).
  - *Estimate:* about 8-11 weeks of lab work, plus review waits.
  - Each phase has a lab-done exit and a review-accepted exit.
  - Nuance is not starting suite work until c2b3b3 and c2b3b4 are done, so review latency, not coding, sets the elapsed time.
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
- **No changes elsewhere.** Nothing in betangel-research changes, and none of Yu's trading policies change.

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
| D-5 | Trading policies are open to change for the suite: AGENTS.md, D1-D5, the typed `/dev/tty` gate, caps and worst-case risk accounting. A change is made only by an explicit proposal, reviewed by Nuance and Astra and approved by Yu. The MVP needs none. |
| D-6 | Commission: Betfair Basic package, 2% (Yu: "Basic 2%"). Whether the label is verified or unverified is R-3. |
| D-7 | Data: the free horse-racing year 2015-05..2016-04 at PRO tier, downloaded by Yu. Nuance ingests and indexes it. |
| D-8 | The £499 live key will be bought when it is needed ("committed to it anyway"). The MVP does not need it. |
| D-9 | The Air's chip is M2. This matters for the later native shell, which runs on the Air (L1), and for any Parallels use. |

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
| R-3 | `user_package_unverified` until Yu checks the package in My Account. |
| R-4 | **Agreed by Yu.** `~/betangel-data/suite.noindex`. Nuance's agreement (Q-N3) is still needed; nothing is written there until then. |
| R-5 | **Yes.** A suite-side, display-only SP parser; no `schemas.py` change. Nuance to confirm (Q-N9). |
| R-6 | **Confirmed.** No rule-generated paper orders in the MVP. Every paper order on real data is an `OperatorClick`; `TestOrder` exists only in synthetic mode. |
| R-7 | **Practise live v1** by default (`v1-live-mirror` caps, live-parity mode). The `practice` profile is still built and selectable. |
| Q-Y8 | Lab-Claude merges a PR after the reviewer routed in section 3.9 has accepted it; UI-only PRs merge on Yu's acceptance alone. Yu can veto or revert any merge. Q-N12 (Nuance's agreement to the routing) is still open. |

**Bet Angel on Yu's Betfair account:** never used (Yu, 2026-10-15), so the design needs no handling for orders or limits shared with Bet Angel. If Bet Angel is ever installed against the account, that needs a fresh review first.

**Q-Y19, Air-side files in this repo** (Yu, 2026-10-16, in the lab session: "Go for D"). Option D records that the R-2 approval already covered the two Air files of section 8.6 item 2, `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`, and rewords rule 1 so its network clause does not cover them (section 3.9, AGENTS.md). Option D's text noted that rewording a binding rule may still need the rule 10 proposal process; Yu has not ruled on that. Lab-Claude reads D, as its text says, as a clarification rather than a widening, so it has drafted no `docs/proposals/` file and has asked Yu to say if one is wanted. Either way the reworded rule is reviewed with PR #5, by Astra and by Nuance (Q-N15).

### 2.3 Hard constraints (lab rules and agreements)

- **No Betfair credentials on the lab.** Nothing runs that logs in or touches the network or an account. The engine refuses to start without `BETANGEL_BETFAIR_FORBID_NETWORK=1`.
- **Licensed data.** It is for Yu's personal internal use only. It is never committed, uploaded or shared. Data and its derivatives stay under `~/betangel-data`, outside every git clone. No 2026 month ever reaches the lab. Tests use synthetic fixtures only.
- **No changes to betangel-research.** The lab clone `~/betangel-research` is fast-forwarded by the Air's script at any time, so the suite never imports from it and never writes into it. That includes `.git/index`, which `git status` can refresh (section 4.2).
- **Python.** `/opt/homebrew/bin/python3` (3.15.0) is frozen for Nuance's certification. It is not used and nothing replaces it. python3.13 (3.13.16) and python3.11 (3.11.17) are available. Node 24 is at `~/.local/bin/node`. There is no Xcode (Command Line Tools only, Swift 6.3.3) and no Apple ID.
- **Nuance's runs.**
  - No suite engine runs during Nuance's announced real backtest runs or PRO ingest. Nuance asked: "A suite elsewhere is harmless but slows the run; please avoid it" (mailbox 08:57Z, A5).
  - No changes under `~/betangel-data`, and no heavy load.
  - Do not use `~/betangel-data/lab-state` (Nuance's proposal, not yet agreed) or `~/betangel-data/logs` (it exists and is not ours).
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
  - By path month: 12,200 fall in 2015-05..2016-04, matching the BASIC index's 12,200 engineering-year WIN markets, and 8 fall in 2016-May. These figures come from a header listing of sizes and path components only.
  - Nuance plans to ingest it after submitting c2b3b3, into a separate data root such as `~/betangel-data/historic-pro`, so that P0's BASIC input descriptor stays unchanged. Nuance asked that `data.tar` and `incoming/` be left as they are.
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
   - **Air and live code.** This lives in a separate repo, or in betangel-research under Nuance, and is **never cloned on the lab**. It uses its own entrypoint package, which the lab's AST and import tests forbid. `guard.py` has no off-switch: no environment variable or config flag disables it, so nothing in this repo can run with the network on.

### 3.2 Threads

- **Actor thread.** Owns all mutable state: the catalogue handle, the open market replay, clock, yield tracker, traded high-water tracker, checkpoints, paper desk, journal and folder. Every command arrives on one `queue.Queue`, so book and paper state need no locks. It ticks every 20-50 ms of wall time.
- **Loader thread.** Builds the catalogue and prescans the market being opened.
  - It prefetches the next race at the same meeting **only in display mode or while paused**. It works in chunks of about 2,000 lines, yields between chunks, and stops when an actor tick overruns.
  - The reason: python3.13 has the GIL. Prescan is pure-Python parse and apply (about 0.75 s of CPU for a median member and about 6 s for the largest), so running it during exact mode adds lag and jitter.
  - A worker process is not an option, because the guard refuses fork and spawn after `seal()` (I-5).
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
  pin.py                      deps checkout lookup, per-file hash check, sys.path append, origin assertion
  rx.py                       THE ONLY module that imports betangel_research (section 4); maps upstream errors to codes
  roots.py                    state roots, the single writer helper (O_EXCL|O_NOFOLLOW, 0600/0700)
  release.py                  bin/suite release, and the RELEASE.json check at every launch from a copy (I-18)
  runmarker.py                the agreed run marker (section 6.8)
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
tools/       vendor_research.py hygiene_scan.py pre-commit
             export_ticks.py (writes ui/ticks.json from the pinned CLASSIC ladder)
             uisnap/uisnap.swift (section 11)
             stage/ suite-viewer-setup.sh air-viewer-selftest.sh air-ssh-config.snippet suite-alias.zsh README.md (staged for Yu, section 8.6)
docs/        DESIGN.md threat-model.md keymap.md data-handling.md proposals/NNN-*.md
.gitignore   *.bz2 *.tar *.sqlite* *.jsonl exports/ run/ screenshots/ (synthetic ones under docs/synthetic/)
```

The repo root holds no top-level `.py` file; a test enforces this. That matters because discovering tests with `-t .` puts the root on `sys.path`.

**Phase 0 as built.** `data/`, `replay/` and `paper/` do not exist yet: the synthetic replay lives in `engine.py` and `synthetic.py`. `ui/` holds `index.html`, `app.js`, `ladder.js`, `grid.js`, `stream.js`, `format.js`, `style.css`, `manifest.json` and `ticks.json`. The keymap is in `app.js`; there is no `keys.js`, `chart.js` or `sounds/` yet. Of `docs/`, only `DESIGN.md` and `data-handling.md` exist.

### 3.5 Dependency on betangel-research

The pin is a **read-only, network-free local clone**:

1. `tools/vendor_research.py <full-sha>` is run by hand: by lab-Claude, never automatically.
   1. It runs `git -C ~/betangel-research cat-file -e <sha>^{commit}`, a read-only object lookup. If the commit is not there yet, it stops and asks you to wait for the Air's fast-forward. It never fetches.
   2. `git clone --no-checkout --no-hardlinks ~/betangel-research ~/.local/share/betangel-suite/deps/betangel-research-<sha12>.partial`, a local clone with no network.
   3. `git -C <dir> checkout --detach <sha>`, then `git -C <dir> remote remove origin`, so no later command can fetch from the moving clone.
   4. Compute the sha256 of every allowlisted file (section 4.1) plus `research/experiments/backtest-p0-bsp-v1.json`, which holds the month roles. Write them into `pin/betangel-research.json` (on a pin bump) or check them against it (on a fresh machine).
   5. Rename the directory into place and `chmod -R a-w` the working tree.
2. **Rules.**
   - Never `git worktree add`, which would write into the deploy clone's `.git`.
   - Never a submodule over the deploy key.
   - Never `sys.path` pointing at `~/betangel-research`.
3. **Why a clone and not `git archive`.** A real checkout lets the oracle `run_paper_replay` record a `git_revision` through `receipts.git_state` (receipts.py:132), and lets the upstream offline suite run in its native layout on a pin bump. A `git archive` into a read-only directory is the fallback if Nuance prefers no `.git` directory. Either way nothing is written into `~/betangel-research`.
4. **At startup.** `pin.py` checks the files against `pin/betangel-research.json` and refuses with `pin_mismatch` if they differ; hashing about 25 files takes a few ms. No git runs at startup. Then:
   - it **appends** the deps directory to `sys.path`; it never inserts at index 0, so the standard library cannot be shadowed;
   - it asserts that `Path(betangel_research.__file__).resolve()` lies inside the deps directory.
   
   `receipts.code_hashes` covers only the package root and `betfair/*.py` (receipts.py:121-125), which is why the suite hashes `backtest/*.py` itself.
5. **Pin bumps.** A bump is a suite PR. It lists the diff of allowlisted files and runs:
   - the contract test (section 4.5);
   - the upstream offline suite at the new commit, from the deps clone: `PATH=/opt/homebrew/bin:$PATH BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 python3.13 -B -m unittest discover -s tests`, never during an announced Nuance run;
   - the suite's own tests.
   
   Nuance reviews every bump that changes an allowlisted file.

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
  test|uisnap) TMP="$HOME/.local/state/betangel-suite/tmp" ;;
  *)           TMP="$HOME/betangel-data/suite.noindex/tmp" ;;   # created 0700 by _launch.py after the run-marker check
esac
exec /usr/bin/env -i HOME="$HOME" USER="$USER" LANG=en_GB.UTF-8 PATH=/usr/bin:/bin \
  TMPDIR="$TMP" SQLITE_TMPDIR="$TMP" SUITE_VIA_SSH="$VIA_SSH" \
  BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 \
  /opt/homebrew/bin/python3.13 -I -S -B "$ROOT/bin/_launch.py" "$@"
```

- **Phase 0's `bin/suite`** differs from this listing in three ways:
  - it refuses to run with `HOME` unset (`HOME="${HOME:?}"`), and passes `USER="${USER:-}"`;
  - while `roots.STATE_ROOT_AGREED` is False (AGENTS.md, Phase 0 status A), both `TMP` branches name `$HOME/.local/state/betangel-suite/tmp`, so every command uses it, and `vendor` joins `test` and `uisnap` in the first branch;
  - `test --py311` runs `/opt/homebrew/bin/python3.11` instead of python3.13.
- **The SSH checks catch accidents, not a determined same-uid process.**
  - The Air agent key is a full shell with no forced command, so `SSH_ORIGINAL_COMMAND` is unset there too.
  - These checks stop `open` or `--print-url` from running over SSH.
  - `ssh-session` accepts `--port N` for tests only (N = 0 picks a free port). The forced command passes no arguments, and an SSH client cannot add any, because a requested command is refused (`refused:ssh_original_command`).
  - The rest rests on the agent-conduct rules (section 3.9, rule 6).
- **Release copies.** `_launch.py` resolves its root with `realpath`, so `app/current` runs exactly one copy. A root under `~/.local/share/betangel-suite/app` must be `app/<tag>` and match its `RELEASE.json` before any command runs, `stop` included (section 8.6); any other root is a working checkout.
- **`-I` and `-S`.**
  - `-I` implies `-P`: neither the script directory nor the cwd is put on `sys.path`. So `_launch.py` appends the repo root itself, and `pin.py` appends the deps clone.
  - `-S` drops Homebrew's `site-packages`, so a stray package there cannot shadow `betangel_suite` or `betangel_research`.
  - The suite and betangel-research are stdlib-only. Upstream checks this for `betfair/*.py` at tests/test_betfair_boundaries.py:297 and for the backtest package at tests/test_betfair_backtest_boundaries.py:949.
- **`env -i`.** Drops any inherited `BETFAIR*`, `BETANGEL_BETFAIR_*`, `PYTHON*` or `SSH_*` variable. Only `HOME`, `USER`, `LANG=en_GB.UTF-8`, `PATH=/usr/bin:/bin`, `TMPDIR`, `SQLITE_TMPDIR`, `SUITE_VIA_SSH`, `BETANGEL_BETFAIR_FORBID_NETWORK=1` and `PYTHONDONTWRITEBYTECODE=1` are set.
- **Temporary files.**
  - `env -i` would otherwise leave `tempfile.gettempdir()` at `/tmp`.
  - Homebrew SQLite 3.54.0 is built with `TEMP_STORE=1`, so large sorts can spill temp files to SQLite's search path. Those would be licensed derivatives outside `~/betangel-data`, opened in C where the audit hook cannot see them.
  - So `TMPDIR` and `SQLITE_TMPDIR` point at a 0700 directory inside the suite root, created only after the run-marker check (section 6.8). Every connection also runs `PRAGMA temp_store=MEMORY`.
- **Python 3.13 is primary.** Tests also run on `/opt/homebrew/bin/python3.11`, matching the upstream syntax floor.
  - The engine refuses to start on any other major version, and in particular on 3.15. It is refused because 3.15 is frozen for Nuance's certification, and so that one interpreter (3.13, with 3.11 as the floor) is the tested one.
  - Nothing installs or upgrades an interpreter. `session.json` records the interpreter version.
- **Tests.** `bin/suite test [--py311] [--heavy] [-v] [-k PATTERN] [-j N]` runs `unittest` over `tests/` from the repo root under the same environment. The test modules are spread over N worker interpreters (default 3, at most 4), whole modules each; `-j 1` runs them in the runner itself. The UI's `node:test` files run from `tests/test_ui_assets.py`, which names each `ui/tests/*.test.mjs`, because `node --test ui/tests` (a directory) fails on node 24. Section 11 has the fast and heavy tiers.

### 3.7 State roots (proposed; R-4 needs Yu's and Nuance's agreement)

| Root | Mode | Contents | Licensed? |
|---|---|---|---|
| Indexed data roots, for example `~/betangel-data/historic-pro` (Nuance's, read-only to the suite) | as is | raw, manifests, index | yes |
| `~/betangel-data/suite.noindex/` (the **suite root**) | 0700 | `catalogue/<index_head_sha256>.sqlite`, `sessions/<YYYY>/<MM>/<session_id>/{journal-paper.sqlite, commands.jsonl, session.json, report.json}`, `ledger/viewed-markets.jsonl`, `reports/` (problem reports, codes only), `exports/`, `logs/` (codes and counts only), `private/` (full tracebacks; agents never read it), `tmp/` | derivatives: yes |
| `~/.local/state/betangel-suite/` | 0700 | `config.json`, `prefs.json` (UI preferences only), `install-salt` (Phase 0 adaptation B), `run/{engine.lock, engine.pid, STOP, control.sock}`, `tmp/` (synthetic tests; in Phase 0, every command), `uisnap/build/<sha256>/` (the uisnap `swiftc` build, plus a shared `module-cache/` of about 233 MB), `uisnap/out/<UTC stamp>/` (synthetic PNGs and `report.json`) | no |
| `~/.local/share/betangel-suite/deps/betangel-research-<sha12>/` | read-only | pinned upstream code | no |
| `~/.local/share/betangel-suite/app/<tag>/` + `current` symlink | owner-only read-only: files 0400, executables 0500, directories 0500; `app/` 0700 | the reviewed release copy that every command Yu runs uses (section 8.6) | no |

Phase 0 creates only `run/engine.lock` and `run/control.sock` in `run/`: no `engine.pid` or `STOP` yet.

- **Rules for the suite root:**
  - it must pass `archive.check_data_root` (archive.py:273): outside the repo and every worktree;
  - every derived path goes through `path_guard.guard_path` (path_guard.py:58; `prospective=True` for new files), which refuses the repo's live-state and certificate trees. The suite never reads the deny list itself; it uses only `guard_path`, `PathDenied` and `denied_sequence` (path_guard.py:25-27);
  - a single writer helper refuses any write outside the roots above.
- **Never touched:**
  - `~/betangel-data/lab-state`, `~/betangel-data/logs`, `incoming/`, and anything under a data root for writing;
  - `~/Library/Application Support/betangel-research/betfair` and `~/.config/betangel-research`;
  - the Keychain.
- **Why `~/betangel-data/suite.noindex`.**
  - It sits beside the data roots, so Nuance's discovery never sees it. That discovery is `archive_shas(root)` over `<root>/manifests` (market_index.py:927).
  - The `.noindex` suffix keeps Spotlight from indexing the suite's text derivatives (CSV exports, `session.json`, `report.json`, `commands.jsonl`). Yu is also asked to add all of `~/betangel-data` to Spotlight Privacy (Q-Y15), which Nuance called sensible (mailbox 08:57Z, B3).
  - Checkpoints and replay buffers live in memory only, which keeps on-disk derivatives to the catalogue, journals, ledger, reports and exports.

### 3.8 Configuration

`~/.local/state/betangel-suite/config.json`, with defaults in `betangel_suite/config.py`:

| Key | Default | Notes |
|---|---|---|
| `data_roots` | `[]` until Nuance names the PRO root (Q-N4), then `["~/betangel-data/historic-pro"]` | Each must pass `archive.check_data_root`. With no root, the engine runs synthetic mode only. The BASIC root is used only by explicit counts-only commands (section 5.1). |
| `state_root` | `~/betangel-data/suite.noindex` | R-4 |
| `port` | 8765 | loopback only. `ssh-session`'s forced command requires 8765, the viewer key's port (`viewer_port_mismatch`; section 8.6 item 2) |
| `frame_hz` | 10 | 5-20 |
| `cap_profile` | `v1-live-mirror` | or `practice` (section 7.2; R-7) |
| `commission_source` | `user_package_unverified` | R-3 |
| `research_months_ruling` | `null` | A ruling id. While it is null, research months are hidden and not written to the catalogue (section 5.3). |
| `run_marker` | `~/.local/state/lab-runs/ACTIVE` (proposed; agreed with Nuance) | section 6.8 |
| `watch_grace_s` | 600 | pause-unless-watched grace (section 8.6); accepted 60-3600 |
| `max_session_s` | 14400 | maximum session time (4 h) for every engine (`serve`, `open`, `ssh-session`), measured from engine start; the session then ends with reason `max_session` (section 8.6); accepted 600-86400 |

- **Paper config.** It is `deepcopy(config.DEFAULTS)` (config.py:27-72), with the active cap profile merged in, plus:
  - `orders.paper.commission_rate = 0.02` and `commission_source`;
  - `orders.customer_strategy_ref` set to the ref the journal intents use: `suite-click` for operator sessions and `suite-test` in synthetic test mode.
  
  So V11 (validate.py:171-173), the config hash and the journal all agree. The DEFAULTS value is `bar-manual` (config.py:57), and the journal fold takes the ref from the intent (journal.py:620, :752).
- **Validation.** It is checked once at startup by the repo's own `config.validate_config` (config.py:254), against `paths.StatePaths(home=<suite root>/repo-home, root_override=<suite root>/repo-home/state)`. That override is accepted only with FORBID_NETWORK set (paths.py:58-72). Nothing is created; `StatePaths` creates directories only in `ensure()`.
- **Git calls during validation.** Validation spawns `git -C <dir> rev-parse --is-inside-work-tree` through `paths.require_outside_worktrees` (paths.py:149, :158; config.py:224-236). So it runs inside the audit hook's startup phase, which allows exactly that argv (section 10).
- **Recorded as a hash only.** The validated config is never written whole into `session.json`, `report.json`, a journal note or `commands.jsonl`; only its `canonical_sha256` is. The reason is that every upstream writer the suite reuses runs `secret.refuse_forbidden` (journal.py:289; receipts.py:183, :211). That raises `SecretLeak` for any key, at any depth, that normalises to `session`, `token`, `headers`, `authorization`, `cookie`, `appkey` and similar (secret.py:114-133), and `config.DEFAULTS` has a top-level `session` section (config.py:41).

### 3.9 Development workflow and the suite's AGENTS.md

- **Branches and PRs.** Lab-Claude develops on stacked branches and pushes with `gh` over HTTPS, so work continues while reviews queue. Review routing is agreed up front (Q-N12, Q-Y8):
  - Astra reviews `guard.py`, `rx.py`, `errors.py`, `release.py`, `runmarker.py`, `api/`, the launcher, the boundary tests, the scanner and pin bumps (the table in AGENTS.md). Phase 0c's review plan also sends uisnap (`uisnap.py`, `tools/uisnap/`), the staged viewer scripts (`tools/stage/`), `cli.py` and `roots.py` to Astra; whether the table should name them is open (Q-N12);
  - Nuance reviews the data and paper paths;
  - UI-only PRs (`ui/` with no change to routes or the command enum) need only Yu's acceptance.
- **Collab.** Edit tasks use `root_path=/Users/user/betangel-suite`.
- **Upstream changes.** Any betangel-research change goes to Nuance as a proposal (section 14).
- **Yu's feedback channel.** Yu's acceptance and feedback reach lab-Claude only in two ways:
  - in a lab-Claude session that Yu types into (on the lab, or one Yu opens from the Air);
  - in an acceptance checklist file that Yu edits directly.
  
  Relays from Nuance or the mailbox are context, not acceptance.
- **The suite's AGENTS.md (binding on every agent):**
  1. **Paper-only MVP.** No credentials, Betfair API, network or live code. Never a "temporary" live endpoint. Later live and Air code never lives in this repo.
     - **The two R-2 viewer files are not network code under this rule** (Q-Y19, section 2.2.1). Yu chose option D: the R-2 approval already covered the two Air files of section 8.6 item 2, `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`, so the network clause does not cover them. This covers these two files and nothing else. Option D's text also says that rewording a binding rule may need the rule 10 proposal process; Yu has not ruled on that (section 2.2.1, Q-N15).
       - The limits these files keep (section 8.6): they serve only the viewer tunnel. The snippet is the Air's `Host lab-suite` block, and the self-test logs in only to that Host, over LAN SSH with the viewer key only, never a password, and uses `nc` only on the Air's own `127.0.0.1`. They hold no credentials and no Betfair API code. They run only on the Air, which takes them only from GitHub at the reviewed merge commit's SHA; on the lab only the test harness runs the self-test, with fake `ssh` and `nc`.
       - Rule 1 is otherwise unchanged: other Air-side code and all other network code stay barred as before. Admitting more, or widening these two files, is a scope widening under rule 10.
  2. **Imports.** Only `rx.py` imports betangel_research, and only from the allowlist.
  3. **Orders.** Every paper order on real data is an operator click (the OperatorClick rule, section 7.1). Scripted orders (`TestOrder`) exist only in synthetic mode, which refuses every real data root. There are no rule-generated orders.
  4. **Licensed data.** Licensed data and its derivatives stay under `~/betangel-data`. Nothing licensed goes in git.
  5. **Agent conduct.** A model context counts as an upload. Agents (lab-Claude, Nuance, Astra) never put real rows, runner names, prices, market ids or per-market results into their context, Collab, the mailbox, PRs or issues.
     - Diagnostics print codes, counts, salted hashes and timings only.
     - Agents never read `ledger/viewed-markets.jsonl` or `private/`. They use `bin/suite ledger-summary` and `bin/suite diagnose`.
     - Debugging uses synthetic fixtures. Screenshots are of synthetic markets only (uisnap).
     - Any exception needs Yu's explicit OK each time, in Yu's own words, scoped to one report (section 8.7).
  6. **Commands agents never run.** Agents never run `open`, `ssh-session` or `--print-url`. They never POST to `/api/v1/command` or `/api/v1/bootstrap` on an engine with real data roots. `serve` and `open` never print a bootstrap code; only `--print-url` and `ssh-session`, used by Yu, do (`ssh-session` to its own SSH stdout). `stop` is allowed, because it only reduces activity.
     - `bin/suite test` exercises `open`, `--print-url` and `ssh-session` only in temporary HOMEs: with injected openers and piped stdin and stdout, or to see them refused before any engine starts. Nothing runs `/usr/bin/open`, and no test prints a code or a token outside its own pipes. Agents never run these commands otherwise.
  7. **Nuance's runs.** While the run marker exists, no suite engine runs and nothing writes under `~/betangel-data` (section 6.8).
  8. **No credential fields.** The suite UI never has credential fields. Any login prompt inside it is an attack.
  9. **Live-key data.** Paper or practice never runs on live-key data (section 2.3).
  10. **Scope.** Every widening of scope goes through the proposal process (section 14).

---

## 4. Reused betangel-research interfaces

### 4.1 Runtime: only through `rx.py`

**Verified import closure.** Importing the allowlist below with `python3.13 -I -S -B` and FORBID_NETWORK loads 25 `betangel_research` modules (checked 2026-10-15; also imports on 3.11.17):

- the package roots, `stream`, `temporal` and `evaluation`;
- `betfair.{book, config, constants, errors, filters, journal, lifecycle, paper, paths, pnl, receipts, schemas, secret, ticks, validate}`;
- `backtest.{archive, contract, market_index, path_guard}`.

The closure loads no gateway, cli, auth, credentials, transport, api, esa, recorder, killswitch, arming, presence, reconcile, **risk** or **capability**. tests/test_betfair_boundaries.py:22 marks the last two `INTERNAL_ONLY`.

The **upstream closure** loads no `socket`, `ssl`, `http` or `urllib`. The suite's own server does load `socket` and `http`, which is why the audit hook polices them (section 10). `subprocess` is loaded through `receipts` and `paths`, which is why the hook polices it too.

| Module | Interface (as used; signatures exact) | Citation | Suite use |
|---|---|---|---|
| ticks | `LADDER_CLASSIC`; `parse_money(text)`; `parse_price(text)`; `to_hundredths(v)`; `to_pence(v)`; `is_on_ladder(price_h)`; `tick_index`; `tick_offset(price_h, n)`; `ticks_between(a_h, b_h)`; `snap(price_h, direction)` | ticks.py:35, :46, :54, :95, :100, :105, :109, :115, :125, :130 | The 350 ladder rows (exported to the UI as JSON; a JS test checks them), click to price, integer pence and hundredths, and green-up snapping with an explicit direction. |
| constants | `MIN_BET_PENCE_GBP`; `CLASSIC_BANDS`; `MARKET_STATUSES`; `COMMISSION_SOURCES`; `ABSOLUTE_CEILINGS` | constants.py:136, :142, :158, :185, :197-217 | The £1 minimum, ladder bands, status labels, commission label, and cap-profile ceilings. |
| book | `MarketBookCache(*, key_type, app_key_slot, source)` (all required; the suite passes `"historical"`, `None`, `"recording"`); `.apply(msg)` returns the changed market ids; `.snapshot(market_id, *, unreliable_ok=False, stamp=None)`; `.stream_unreliable`; `.has_definition(id)`; `.markets()`; `.counters` | book.py:136, :139, :168, :402-466 (stamp :448), :158, :162, :154, :59-61 | Book reconstruction. Snapshots are taken lazily (section 6.2). Counters appear as counts in diagnostics. |
| book | `replay_market_time(value)` | book.py:68 | Countdown and jump marks from `marketTime`. |
| schemas | `BOOK_SNAPSHOT_KEYS`, `RUNNER_KEYS`, `SNAPSHOT_KEY_TYPES`, `INSTRUCTION_V1_KEYS`, `ORDER_STATES`, `UNRESOLVED_STATES`, `validate_book_snapshot`, `validate_instruction_v1` | schemas.py:18-23, :26, :32, :46, :51, :164, :222 | The contracts that frames and tickets are built against. Missing SP keys (:23) are why the SP tap exists. |
| validate | `validate_place(market_id, instructions, *, book, open_orders, config, mode, now_ns, probe=False, now_monotonic_ns=None, customer_ref=None, customer_order_refs=None)`; `validate_cancel(market_id, cancels, *, open_orders, kill_targets=None)`; `make_customer_ref(now_ns, rng)`; `make_customer_order_ref(now_ns, rng)`; `profit_ratio_ok(size_p, price_h)` | validate.py:290-291, :410, :46, :51, :67 (V9 :102-121; V0 :190-192; V5 :212-219; V6 :220-221; paper V10 :154-163) | Every click is checked against V0-V14 and refusals are shown in plain English. `mode="paper"` is always passed explicitly (it has no default). Refs come from a deterministic rng per session and click. Green-up feasibility. |
| paper | `PaperExchange(params, *, queues=None, state=None)`; `.place(orders, *, book, now_ms, refusal=None)`; `.cancel(orders, cancels, *, now_ms)`; `.advance(open_orders, *, prev_book, book, now_ms, gap=False)`; `.settle(orders, *, market_definition)`; `.queue_state()`; `.export_state()`; `.close_market(market_id, refs)` | paper.py:155-179, :342, :358, :428, :592, :181, :184, :259 | The fill model, driven directly (R-1). `queue_state()` feeds the queue-ahead display. Exported state plus the constructor re-seed traded high-water marks (section 7.4). |
| paper | `PAPER_MODEL`, `PAPER_ASSUMPTIONS`, `PARAM_KEYS`, `REPLAY_STATUS`, `book_time_ms(book)`, `paper_bet_id(ref)` | paper.py:30-57, :59-60, :62, :101, :141 | The "How fills work" panel quotes these verbatim. Every report carries `REPLAY_STATUS`. |
| lifecycle | `TRANSITIONS`; `PAPER_REFUSAL_CODES`; `PAPER_FAILED_CODES`; `transition(order, new_state, *, reason, fields=None)`; `classify_place_report(result, *, sent_refs, orders=None)`; `classify_cancel_report(result, *, sent_bet_ids, orders=None)` | lifecycle.py:39, :72, :74, :103, :243, :306 | Turns paper reports into legal journal moves. A dry-run `transition()` checks the suite-built close lapse and the pending-order withdrawal (section 7.6). |
| journal | `OrderJournal(path, *, mode, clock=SYSTEM_CLOCK, busy_timeout_s=30)`; `.append(kind, payload, *, ..., expect_head)`; `.anchor()`; `.verify()`; `.fold(*, now_ns, submitting_as_unknown=True)`; `JournalFolder(mode).apply(event)` and `.state(*, now_ns, submitting_as_unknown=True)`; `KINDS`; `INTENT_PAYLOAD_KEYS`; `INTENT_SOURCES`; `CLOCK_REGRESSION_NS` | journal.py:303, :313, :483, :437, :410, :444, :689, :726, :837, :80, :95, :97, :93 | One hash-chained paper journal per session, always constructed with the suite `SimClock`. Forgetting it would silently put the journal on wall time, so a test asserts it. An incremental folder is fed by the events `append` returns, and is always read with `submitting_as_unknown=False`, as `_simulate` does (paper.py:884). `state()["orders"]` is a dict keyed by ref (journal.py:842, :869-870). |
| pnl, evaluation | `order_pnl_pence(side, avg_price_h, size_settled_p, runner_result)`; `market_realized(orders, runner_results, *, commission_rate)`; `EXCLUDING_RESULTS`; `evaluation.settled_market_costs` | pnl.py:24, :38 (Rule-4 exclusion :53-54, dead heat :55-56, commission rounding :79-82), :15; evaluation.py:136 | What-If, settlement at 2%, the official exclusion, and the indicative Rule-4 figure (section 7.9). |
| config | `DEFAULTS`; `validate_config(config, *, paths)` | config.py:27-72 (orders :56, caps :58-62, rules :63, paper :65-66), :254 | The paper config and cap profiles, validated by the repo's own validator (section 3.8). |
| paths | `FORBID_NETWORK_ENV`; `network_forbidden()`; `overrides_allowed()`; `StatePaths(home=..., root_override=...)` | paths.py:22, :29, :36, :58-72 | Startup refusal without FORBID_NETWORK; the validation-only override. `.paper.lock` (:82) is never taken. |
| receipts | `utc_from_ns(ns)` (int only); `parse_utc_ns(text)`; the `SystemClock` protocol; `canonical_sha256`; `file_sha256`; `atomic_write_json`; `append_jsonl`; `strict_json_loads` | receipts.py:29-34, :52, :78, :104, :113, :180, :208, :247 | The sim clock on the pt axis (always `ms * 1_000_000`, never a float), session hashes, atomic 0600 writes, and strict request bodies (duplicate keys and NaN refused). |
| secret | `register(value)`; `assert_clean`; `refuse_forbidden` (called by the writers above) | secret.py:20-25, :114-133 | The session token and bootstrap codes are registered, so a journal or receipt write that contains one is refused (journal.py:296; receipts.py:185, :214). |
| backtest.archive | `CHUNK_BYTES`; `LIMIT_CEILINGS`, `Limits.stricter(**changes)`, `DEFAULT_LIMITS`; `market_month`; `month_gate(month)`; `parse_member_path(name)`; `check_data_root(path)`; `HashingReader`; `safe_path`; `safe_target(root, sha, member_path)` | archive.py:95, :110-132, :168, :179, :200, :209, :245, :273, :383, :643, :662 | Read-only, symlink-safe, bounded, month-gated member loads. The suite uses stricter limits: DEFAULT allows 8 GiB decompressed per member (archive.py:120). `market_month` can return `None` (archive.py:200-206), and `month_gate(None)` raises `TypeError` (archive.py:211), so the suite refuses `None` first. |
| backtest.market_index | `HEAD_FILE`, `MARKETS_FILE`; `loads_strict(data)`; `market_sort_key(id)`; `load_manifest(root, sha)`; `archive_shas(root)`; head `files[]` entries with `status` and `complete_before_pt` | market_index.py:142-143, :215, :220, :225, :927, :720-724 (refused), :740-741 (indexed or unreadable) | Catalogue build and the strict line parse. Readability comes from the head's `files[]`, never from `evaluator_only_outcome`. |
| backtest.path_guard | `guard_path(path, where, prospective=False)`; `PathDenied`; `denied_sequence(path)` | path_guard.py:58, :37, :48 | Every suite path is checked: `guard_path(..., prospective=True)` for new files, and `denied_sequence` where a check without resolving is needed. |
| backtest.contract | `SEALED_HOLDOUT`, `INSPECTED_MONTHS`, `EXPOSED_MONTHS`, `NOT_PROSPECTIVE_DATES`; plus `research/experiments/backtest-p0-bsp-v1.json` `population.splits` | contract.py:154, :155, :159, :167 | Month roles come from the pinned files and are not hard-coded. Engineering (2015-05..2016-04) is visible; research (2023-01..2025-12) is hidden by default. |

### 4.2 Test-only oracles (imported only under `tests/`)

| Interface | Citation | Test use |
|---|---|---|
| `paper.run_paper_replay(recording_paths, orders_path, params, out_dir, *, repo_root, snapshot_reader=None, key_type=None)`; `ORDER_FILE_KEYS` | paper.py:956, :61 | The parity oracle, on **small synthetic fixtures only** (capped at about 2,000 messages and 6 runners). It holds every snapshot in a list (paper.py:991-996); *measured (synthetic)* at about 1.98 GB RSS and 141 s for one 60k-message market. It is never run on real data. `repo_root` is always a temp `git clone --local` of the deps clone, never `~/betangel-research`, because `receipts.git_state` runs `git status --porcelain` there, which can rewrite `.git/index` (receipts.py:132-145; paper.py:956-957, :1053). A test asserts this. |
| `book.snapshots_from_recording(path, *, key_type)` | book.py:526-582 | The oracle for the yield tracker (section 6.2), including 503 windows. |
| `market_index._messages(stream, limits)` (private) | market_index.py:268-297 | Reader parity: one test imports it, so drift is caught on pin bumps. |
| `risk.worst_case_market_loss(orders, outcome_ids, *, hedge_credit=False)`; `risk.exposure_by_market`; `STATUS_EXPOSURE_BASIS` | risk.py:136, :167, :52 | The oracle for the suite's own exposure code, on both bases. Note the default is `hedge_credit=False`. The engine never imports risk (INTERNAL_ONLY, tests/test_betfair_boundaries.py:22). Whether even test-only use is acceptable is a question for Nuance. |
| `archive.ingest_archive(tar_path, data_root)`; `market_index.index_archive(root, sha)` | archive.py:765; market_index.py:870 | End-to-end data tests: a synthetic TAR is ingested and indexed into a temp root. Engine code never calls them (AST test). |

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

`tests/test_upstream_contract.py` fails loudly on a pin bump if any of these drift:

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
| Free PRO year, horse racing 2015-05..2016-04 (EX_ALL_OFFERS, TRD, TV, LTP, MARKET_DEF, SP_TRADED, SP_PROJECTED, tick-by-tick) | Downloaded by Yu to `incoming/data.tar`. Nuance ingests it, probably into `~/betangel-data/historic-pro`. | **The only replay source.** Ladder replay and paper. The engineering year is already "seen", so using it spends no research months. |
| BASIC TAR (GB/IE WIN, 2015-05..2016-04 + 2023-01..2025-12, 1-minute LTP and definitions) | `~/betangel-data/historic` (ingested and indexed) | No UI mode. It is used only for counts-only checks run from the command line, in case the PRO ingest slips: a catalogue build and a reader smoke. Research months stay hidden. |
| Synthetic fixtures | Generated at test time into temp dirs by `tests/fixtures/gen.py` | All automated tests and every screenshot. |

Not on the lab, and never to be put there: the 2017 PRO samples (unless Yu fetches them), and any 2026 month, including the Air's delayed-stream recordings. Each 2026 month is refused by lab rule 4 and by `month_gate`.

### 5.2 Data roots and discovery

- The suite reads a configured list of indexed data roots. Each must pass `archive.check_data_root` (archive.py:273). It never reads `incoming/`.
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
  - **Research months.** While `research_months_ruling` is null, research-month records are **not written** to the catalogue at all; only their counts are stored. Enabling them needs a ruling id from Yu with Nuance and Astra. The id is recorded in the ledger, logged at startup, and shown in the picker.
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
  - Reconciliation with Nuance's trial ledger is done by code that compares salted hashes of market ids and prints only match counts. The format is agreed with Nuance (Q-N11).
- **Agents never see rows** (section 3.9). `bin/suite selfcheck`, `catalogue`, `diagnose` and `ledger-summary` print codes, counts, salted hashes and timings only.

### 5.6 What never goes in git

- **File types:** `*.bz2`, `*.tar`, `*.sqlite*`, `*.jsonl`, exports, runs, screenshots outside `docs/synthetic/`, and any file over 512 KB. Enforced by `.gitignore`, `tools/hygiene_scan.py` and a pre-commit hook.
- **Fixtures:**
  - synthetic only, generated at test time, never committed as binaries;
  - reserved ids: markets `1.999xxxxxx`, events `99xxxxxx`, selections `9xxxxxxx`;
  - venue "Synthetic Park" and runners "Synthetic 1..n".
  
  The scanner fails on any `1.1[0-9]{8}`-shaped market id, or any runner-name table, outside that namespace. In synthetic mode the engine refuses non-synthetic ids and every configured real data root.
- **Scanner names.** The scanner compares its protected names (data-root components, forbidden directories, betangel-research copies, `betangel-data` in a link target or text) case-insensitively, with `casefold()`, because the lab's APFS volume folds case. Findings for runner data (`runner_table`, `runner_record`, `stream_record`), like the file-level data codes, withhold the file name.
- **Writing:** no real-market screenshots, prices, names or ids in PRs, issues, Collab or the mailbox.

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
- **Values.** It keeps the latest values at V. Quoted `"NaN"` and `"Infinity"` SP strings count as missing.
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
  - A run-active marker is agreed with Nuance, outside `~/betangel-data` and not under the unagreed `~/betangel-data/lab-state`. The proposal is `~/.local/state/lab-runs/ACTIVE`, written by Nuance's run wrapper.
  - It is checked first by `_launch.py`, before anything is created under `~/betangel-data`.
  - It covers both real backtest runs and the PRO ingest and index.
- **At start.** The engine and every real-data command (`catalogue`, `selfcheck`, `diagnose`) refuse to start while the marker exists. An unreadable marker, or an unreadable marker directory, counts as present. `serve`, `open` and `ssh-session` check it again after taking `engine.lock`, so a marker written while they start refuses the start.
- **Mid-session.** The actor checks the marker every tick, again after it dequeues each command (before running it), and before every journal append or ledger write. If the marker appears:
  - the engine pauses the clock and freezes `PaperExchange`: no advance, no activation, no journal or ledger writes;
  - the UI shows why;
  - the engine exits after a grace period of 30 s without writing.
  
  At the next start, after the run, the session is marked `interrupted_run`. It is not counted as abandoned by Yu.
- **Nuance's side.** Nuance's wrapper writes the marker, then waits until `~/.local/state/betangel-suite/run/engine.lock` is free (at most about 30 s was proposed; as built it can take about 35 s, Q-N3) before touching sources or data. This is a request to Nuance (Q-N3).
- **No automatic work.** The catalogue is rebuilt only on an explicit command, never on a head change, so nothing fires during Nuance's ingest.
- **Until a marker is agreed.** Lab-Claude runs no real-data commands while a run is announced, and Yu is told before starting. **The agreed marker is a Phase 0 exit criterion, and Phase 1b journal writes on real data do not ship without it.**
- **Phase 0 (adaptation E in AGENTS.md).** `stop`, `test` and `vendor` do not check the marker at start; every other command refuses while it exists, and `test --heavy` refuses too. The fast tier therefore runs during a marker. It starts synthetic engines (`serve`, `open`, `ssh-session`) in temporary HOMEs, whose marker checks read the temporary HOME's marker path, not the real one. That sits uneasily with rule 7 of section 3.9 ("no suite engine runs"), so it is an open question for Nuance (Q-N14).

---

## 7. Paper trading

### 7.1 Scope and the operator-click rule

- **What paper supports.**
  - LIMIT/LAPSE, one instruction per click, and whole-bet cancel.
  - Pre-off horse-racing WIN with one winner on a CLASSIC ladder (V9).
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
- **Practice loss limit.** Default £20 per day, mirroring `max_daily_loss`; it is a question for Yu. When the limit is reached, paper is disabled for the rest of the day, with an explanation.

### 7.3 One click, step by step

1. **The UI sends** `{nonce, cmd:"place", selection_id, side, price_h, size_p}`. The handler mints an OperatorClick and enqueues it.
2. **Build the order.** At replay time T (an integer ms), the actor reads `anchor()` (journal.py:437) and materialises `book = materialise(M)` (section 6.2).
   - It builds the instruction v1 `{selection_id, handicap 0, side, price_h, size_p, persistence_type "LAPSE"}` (`validate_instruction_v1`, schemas.py:222).
   - Refs come from `make_customer_order_ref` and `make_customer_ref`, with a deterministic rng `sha256(session_id:click_index)` (validate.py:46-55).
3. **Validation.** Let `state = folder.state(now_ns=T * 1_000_000, submitting_as_unknown=False)`, and `market_orders = [o for o in state["orders"].values() if o["market_id"] == M]`. The fold's `orders` is a dict keyed by ref, so it is never passed as is, as the oracle does at paper.py:884-885. Then:

   `validate.validate_place(M, [instr], book=book, open_orders=market_orders, config=<paper config>, mode="paper", now_ns=T * 1_000_000, customer_ref=cref, customer_order_refs=[ref])` (validate.py:290-291).

   On any failure the click is refused and its rule code is mapped to plain English. Nothing is journaled. The refusal table covers, among others:
   - V0: "unsupported order shape (only LIMIT/LAPSE)";
   - V5: "below £1";
   - V6: "only LAPSE (cancel at in-play) is supported";
   - V8: "would match your own order";
   - V9: "suspended, in-play, not WIN or book invalid", with the sub-reason, for example `book_invalid`;
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

Whether a suite-built `state` is acceptable is a question for Nuance (Q-N7). The proposed upstream helper is U-6.

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
- **MVP: parity only.** Unstamped books are used. The refusal is explained plainly ("no market change for 12 s ...") and counted in the debrief.
- **Cut from the MVP.** The draft 0.1 opt-in "quiet-book relaxation" (`quiet_books_stamped`) is removed. It is revisited only if the debrief counts show it matters (U-8).

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
  
  Unmatched, pending and unknown portions count at their full adverse loss in both bases. Tests check it against `risk.worst_case_market_loss(..., hedge_credit=True/False)` on randomised order sets. Showing both bases makes visible that greening at live defaults would use up the £20 daily cap.

### 7.8 Green-up / close trade (new suite code; an operator action)

- **Inputs.** For the selected runner: W = profit if it wins, L = profit if it loses (integer pence), and p = the current best opposite price.
- **Hedge stake.** `h = (W - L) / p`. Lay h if it is positive; back |h| if it is negative.
- **Rounding.** h is rounded to whole pence in the direction that maximises the worse outcome. Any price snap uses `ticks.snap` with an explicit direction that goes against Yu.
- **Checks.** The stake must be at least £1 (MIN_BET_PENCE_GBP) and pass `profit_ratio_ok` (validate.py:67). If not, the preview says why, for example "green needs £0.62 < £1 minimum".
- **Preview.** It shows both outcomes after the hedge and commission at 2% on positive market totals. It warns that paper takes at most 50% of the displayed size, so the hedge may part-fill and rest. C opens the preview; Enter submits one place.
- **Out of the MVP:** green-all, reverse greening and offsets. Any automatic follow-up order would be automation (P-1).

### 7.9 Rule 4 and honest settlement

- **The exclusion.** `pnl.market_realized` excludes every market with a REMOVED or REMOVED_VACANT runner (pnl.py:15, :53-54) and every dead heat (pnl.py:55-56). That is 49.5% of the engineering-year WIN markets.
- **The debrief** always shows the official paper-v1 result, for example "excluded: rule4_adjustment_not_modelled".
- **Indicative figure.** It appears only when **every matched portion was matched strictly after the market's last removal**, using the pt of the first REMOVED status seen in the stream. In that case Rule-4 deductions cannot apply to Yu's bets. It is labelled "indicative: Rule 4 cannot apply to bets matched after the last removal".
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

- **One session per market attempt**, at `sessions/<YYYY>/<MM>/<session_id>/` (0700):
  - `journal-paper.sqlite` (0600; hash-chained; WAL with fullfsync; *measured* about 4.3 ms per append, about 13 ms per click);
  - `commands.jsonl`: every command with its virtual pt, nonce and result code. It never has a key named `token`, `headers`, `authorization` or `session`;
  - `session.json`, which holds:
    - `session_id` (never a key named `session`), market id, plan, archive and member sha256;
    - the release tag and tree hash, the pin commit and the file-manifest sha, and the interpreter;
    - the paper params' and the validated config's `canonical_sha256` (never the config itself; section 3.8), the commission source and the cap profile;
    - the mode flags (parity, exploration) and the attempt number;
    - the status: `completed`, `abandoned`, `voided_rewound`, `interrupted_run` or `not_closed_in_recording`;
  - `report.json`.
  
  All writes go through `receipts.atomic_write_json`, `append_jsonl` or the journal, which run `refuse_forbidden` and `assert_clean`. Tests write a real `session.json`, a `report.json` and a note through these writers.
- **Positions** come from an incremental `JournalFolder` fed by the events `append` returns (journal.py:483, :689-726). The suite never calls `fold()` per frame (journal.py:444). A test asserts that the folder's state equals `OrderJournal.fold(..., submitting_as_unknown=False)`.
- **Determinism (synthetic mode only).** Re-running `commands.jsonl` as `ReplayedClick`s over the same synthetic member, into a temp journal, gives an identical journal fold and identical results (test). This re-run never runs on real data (R-6).
- **Abandoned sessions.** A session is marked `abandoned` only after its watch grace period expires with nobody watching (section 8.6), or at the next start after a crash. Its journal stays readable.
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
- Practise the learning target Yu chose (R-7). Anything beyond live v1 carries the shadow badge, and anything paper-only is amber.
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
   - The official paper-v1 settlement (gross, 2% commission, net) and the indicative Rule-4 figure where it is exact.
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
   - *As built in Phase 0c:* a read-only tab cannot STOP. Its STOP button is disabled, Q and Shift+Q are ignored, and the server answers 409 `not_controller` (section 9.2 item 8). `bin/suite stop`, and claiming control first, still work. This conflicts with "reachable by key" above; open question Q-Y17.

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

- **How a release is made.** A release is a `git archive` of a tag on the merged main branch, installed after review by one command, `bin/suite release <tag>` (guard mode release), run in the clean main checkout:
  - It refuses a dirty tree (tracked or untracked files), git filter drivers in the repository's own config (`release_git_filter`), a gitlink in the index (`release_gitlink`: `git status` would enter that repository and run filters from its own config; it is checked first with `ls-files --stage -z`, and `status` never enters a submodule), a tag that is not `refs/tags/<tag>`, a tag commit that local main does not contain, an existing `app/<tag>`, and the tag name `current`. Nothing is fetched.
  - It git-archives the tag's commit id into `app/.<tag>.partial`, and recomputes the git tree id from the copied bytes; it must equal the commit's tree.
  - It writes `RELEASE.json`: `{format, tag, commit, tree, files: {path: sha256}, executables}`.
  - It makes the copy owner-only read-only (section 3.7), checks the run marker again, renames the copy to `app/<tag>`, and switches `app/current` atomically through `app/.current.partial`.
  - **Every launch from a copy**, every command included (`stop` too), checks `RELEASE.json`: the sha256s, the executable bits, no write bit, the owner, no extra entries, and the recomputed tree id. Any mismatch refuses with a `release_*` code (`wrong_owner` for the owner check).
  - A release copy cannot make releases itself (`release_not_a_checkout`). Making the first release, after review, is Yu's decision (AGENTS.md, Phase 0 status D). Whether agents may ever run `release` is open (Q-Y18).
- **What a working checkout can do.** An engine whose code is not a release copy with a matching `RELEASE.json` runs in **synthetic mode** only: `serve`, `open` and `ssh-session` refuse every non-synthetic data root there. Headless counts-only commands (`selfcheck`, `catalogue`, `diagnose`, `ledger-summary`) may run from a working checkout.
  - *In Phase 0* every engine refuses every data root, a release copy's included (`synthetic_only`), and no release copy exists until Yu makes the first one. So Yu looks at synthetic markets from a working checkout.
- **Why.** Yu's viewing of licensed data never runs unreviewed code. `session.json` records the release tree hash.
- **Iteration.** In Phase 1a, Yu can look at work in progress in synthetic mode.

1. **The lab's own screen** (no change needed; available from Phase 0).
   - Yu runs `suite open --print-url` and pastes the printed URL, `http://127.0.0.1:8765/#c=<bootstrap code>`, into a Safari Private window within 120 s.
   - Plain `suite open` hands the URL to `/usr/bin/open` instead, before its guard seals. That opens the default browser in a normal window, and the URL is never printed.
   - With no engine running, `open` starts one and stays in the foreground, because it hosts the engine. It prints `opened port=<n>`.
   - If an engine is already running, `open` takes it over through the control socket: the engine pauses, and every earlier code and token dies. `open` gets a fresh code, hands it on the same way, prints `attached port=<n>` and exits.
   - `serve` refuses `--print-url`, and `open` and `--print-url` are refused over SSH (section 3.6). `serve` and `open` print `ended reason=abandoned` or `ended reason=max_session` for those two ends only.
   - The page POSTs the code to `/api/v1/bootstrap`, gets a session token, keeps it in JS memory only, and strips the fragment with `history.replaceState`.
   - On the lab screen alone a second tab is never read-only, because both forms of `open` take the session over. No lab command mints a second code without a takeover (the control socket's `new_code` has no CLI caller). A read-only tab (section 9.2 item 8) needs a code from Enter in an `ssh lab-suite` window, so `claim_control` can be checked only after the viewer install (item 2).
   - After the data downloads, Yu should sign out of historicdata.betfair.com in the lab's Safari. The lab should hold no Betfair session (mailbox 08:57Z, B4).
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
     - **`ClientAlive*`** makes sshd notice a dead Air connection within about a minute. It applies to every SSH session, which is why it is in the same approval.
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
     - `ProxyCommand none`, `ProxyJump none` and `PermitLocalCommand no` stop a later `Host *` block from adding a proxy or a local command. ssh keeps the first value it reads, so the block goes at the top of `~/.ssh/config`, above any `Host *` or `Match` block. The self-test refuses to start unless `ssh -G lab-suite` shows the seven hardening lines (`ControlMaster`, `ControlPath`, `ControlPersist`, `IdentityAgent`, `ProxyCommand`, `ProxyJump`, `PermitLocalCommand`) and the three authentication lines in force.
   - **Use.** Yu types `ssh lab-suite` on the Air. Do **not** use `-N`: a forced command runs only when a session channel is opened.
     - `bin/suite` checks `SSH_CONNECTION` and `SSH_ORIGINAL_COMMAND` before `env -i` (section 3.6).
     - `ssh-session` without `--port`, which is how the forced command runs it, serves or attaches only on 8765, the port of `permitopen` and the `LocalForward`. Another config `port` refuses with `viewer_port_mismatch` before any engine starts, and so does a running engine on another port (from `serve --port N` or `open --port N`), before any takeover.
     - It prints a single-use URL (`http://127.0.0.1:8765/#c=<code>`; code valid for 120 s) to that session's stdout only.
     - Yu pastes the URL into a Safari Private window (Cmd-click would open a normal window).
     - Pressing Enter in the ssh window prints a fresh code, for example after a page reload.
   - **What the ssh window shows.** The session's stdout carries only these lines (`api/sshsession.py`):
     - the URL, at the start and again for every Enter;
     - `heartbeat h:mm:ss` every 15 s: the time since this viewer attached;
     - one `ended reason=<code>` when the viewer's part ends: `superseded`, `engine_gone`, or the engine's own end reason (`stopped`, `abandoned`, `max_session`, ...).
     
     ssh shows the session's stderr in the same window. It carries only code-only lines, and these are not attacks:
     - `http:<status>:<code>` or `http:error:<class>` from the engine's HTTP server, when this `ssh-session` hosts the engine: for example `http:401:bad_code` after a page reload;
     - `refused:<code>` or `error:<class>` when `bin/suite` refuses or fails: for example `refused:run_marker_present` during a Nuance run.
     
     Anything else the session prints is an attack, for example text asking for a password, or a URL with another host or port (see the trust boundary below).
   - **Session lifetime: pause unless watched** (an MVP invariant, I-19; `api/lifetime.py`):
     - The actor auto-pauses when the controller tab's stream drops or the page reports `visibilitychange` hidden. While hidden, the page asks again on any stream message that shows the clock running (a Play accepted just before hiding, or a pause that failed), one request at a time, and stops asking after `not_controller`.
     - `ssh-session` writes the heartbeat line every 15 s and reports it to the engine. A failed write, a write that stdout does not take within 5 s (an SSH channel still open that nobody reads; a blocking write would hold the engine's loop, its lifetime checks and its stop), stdin EOF or SIGHUP means the viewer has left, and a viewer silent for 60 s counts as away. The engine then pauses and keeps the session for `watch_grace_s` (default 10 min) instead of stopping.
     - With no engine running, `ssh-session` hosts the engine in its own process. So that process, and `ssh lab-suite`, lasts until the engine ends, and then prints the end reason (unless it has already printed `ended reason=superseded`). An `ssh-session` attached to a running engine exits at once on stdin EOF, while the engine keeps the grace.
     - **Signals.** Under a hosting `ssh-session`, SIGHUP means the viewer left (the grace runs), and SIGTERM and SIGINT stop the engine. An attached `ssh-session` treats all three as the viewer leaving.
     - A new `ssh lab-suite` (or `suite open`) during the grace **takes over** through the control socket. The engine pauses, invalidates every earlier code and session token, and issues a fresh code. It is not refused. Journalling a note of the takeover is deferred to Phase 1b, because Phase 0 has no journal.
     - **Nobody watching** means the terminal viewer is away and no tab is streaming. Only when nobody has watched for the whole grace is the session marked `abandoned` and the engine stopped.
     - A takeover by `suite open` hands the session to the lab's screen, which has no terminal viewer. Such a session never ends as `abandoned`. It ends on `suite stop`; on a stop signal to the process that hosts the engine (SIGTERM or SIGINT, and SIGHUP too when `serve` or `open` hosts it, as when its Terminal window closes); at the maximum session time; when the run marker appears (reason `run_marker`, after the 30 s grace of section 6.8); or on an engine failure. In Phase 0 the page's STOP only pauses the engine. The same holds for an engine started by `serve` or `open`, until an `ssh-session` takes it over.
     - The maximum session time, `max_session_s` (default 4 h), applies to every engine (`serve`, `open`, `ssh-session`), measured from the engine's start. The session then ends as `max_session`.
   - **What the key can and cannot do.** Lab-Claude stages an Air-side self-test, `air-viewer-selftest.sh`, which Yu runs right after installing the key (Nuance may start it, but only Yu types the passphrase).
     - It refuses to start unless `ssh -G lab-suite` shows the block's host, user, address family, single identity, `LocalForward`, `AddKeysToAgent`, `IdentitiesOnly`, `ExitOnForwardFailure` and `StrictHostKeyChecking` values, the three authentication lines, and all seven hardening lines. It does not check `UseKeychain`, `RequestTTY` or `ServerAliveInterval`.
     - It makes nine probes over five logins, and reports each one as refused or ALLOWED. A probe counts as refused only with evidence that the viewer key logged in and the lab refused.
     - The probes: a requested command (the launcher refuses it); a PTY; `-L` to another port, to another host, to `localhost:8765` (`permitopen` names `127.0.0.1` only) and to a Unix socket; `-W host:22`; `-R` to a TCP port (port 0) and to a Unix socket.
     - The verdict is PASS only if all nine were refused. On FAIL, Yu runs the undo on the lab at once.
   - The existing Air agent key keeps `no-port-forwarding` and is never used for Yu's UI. Removing the viewer line revokes access.
3. **Alternative: macOS Screen Sharing** on the lab, which Yu turns on in System Settings. It is broader: full desktop control from the LAN.
4. **Not recommended:**
   - binding the engine to the LAN (Bet Angel's port-9000 anti-pattern);
   - a VPN or exit node (lab rule 5);
   - copying licensed data to the Air;
   - running the MVP engine on the Air next to the Betfair credentials.

**The trust boundary.** The tunnel makes lab-served JavaScript run in Yu's Air browser. That JS is written by lab-Claude and is replaceable by any lab process running as `user`; `chmod a-w` does not stop the owner. This is the only lab-to-Air code path: the two Air files of item 2 reach the Air from GitHub at the reviewed merge commit, never from the lab. Rule 1's network clause does not cover them (section 3.9; Yu's ruling on Q-Y19).

A buggy or tampered page could show a fake Betfair login and send what Yu types to the lab. The CSP cannot prevent that, because the lab sets it. Hence:

- the suite UI never has credential fields, so any login prompt in it is an attack;
- use a Private window, or a profile with no Betfair login, on both machines;
- Air-side components never listen on TCP loopback (Unix sockets only), so this page cannot reach them;
- the later native shell uses `WKWebsiteDataStore.nonPersistent()` and no `console.log` of data.

**The forced command is same-uid too.** Any lab process running as `user`, an agent included, can replace the forced command, the release copy it runs, the shell startup files sshd runs before it, and `~/.ssh/authorized_keys` itself. That file holds the viewer line's `from=`, `restrict`, `permitopen` and `command=` options, so such a process can also widen what the key may do. The copy's read-only modes stop accidents, not the owner.

- Only the root-owned drop-in is beyond such a process: no `-R`, no Unix-socket forwarding and no listeners. It keeps `AllowTcpForwarding local`, so with `permitopen` edited away, `-L` to any host and port would work again.
- The Air self-test confirms the key's limits only when it runs, at install time.
- Such a process could also print anything in the `ssh lab-suite` window and serve anything on the lab's `127.0.0.1:8765`. So Yu treats anything in the window beyond the lines listed under "What the ssh window shows" (item 2) as an attack, closes the window and runs the undo.

**What reaches the Air.** Replayed prices appear on the Air's screen and in the browser's memory. In a normal window, Safari History, iCloud History and iCloud Tabs would also sync the URL and `document.title`. Safari may also keep page thumbnails (*inference*). The Private window, the static title and the single-use code address this. It is still personal internal use, and the question is put to Yu anyway (Q-Y2).

### 8.7 Feedback and problem reports

- **Report a problem.** A `report_problem` command (a button, with an optional fixed category) writes `reports/<session_id>-<n>.json` under the suite root. It contains:
  - the session id and attempt;
  - the virtual pt as an offset from the scheduled off;
  - the last N command codes;
  - counters, `invalid_reason` codes and frame timings.
  
  It contains no names, prices or market ids.
- **Diagnose.** `bin/suite diagnose <report>` replays that session's member headless to the reported offset, reads the existing journal, and prints codes and timings only. It does not re-execute orders on real data (R-6).
- **Per-incident consent.** When structure is not enough, lab-Claude asks Yu, in Yu's direct channel (section 3.9), for an OK scoped to one report and named fields. Yu's answer is recorded in the report folder. Nothing beyond that scope is read.
- **Acceptance.** Yu works through each phase's checklist in that channel. Relays from Nuance are context, not acceptance.

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
   - So a read-only tab cannot STOP, which conflicts with section 8.2 item 8. `bin/suite stop`, and claiming control first, still work. Open question Q-Y17.
9. **Errors are codes only.** No tracebacks, request bodies, data rows or identifiers. Upstream exceptions are mapped at the `rx.py` boundary:
   - The caught exceptions are `IndexProblem`, `ArchiveProblem`, `PathDenied`, `ValueError` and `JournalError`. These embed member paths, which contain real event and market ids: for example `where = f"raw:{member['path']}"` (market_index.py:726) and `_label(name)` (archive.py:298, :348, :815).
   - The boundary keeps only the reason after the last colon, from a closed enum. Any identifier is replaced with a salted hash; the salt is per install and kept under the suite root.
   
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
| **Lab-served JS running in Yu's Air browser** (the only lab-to-Air code path) | No credential fields (any login prompt is an attack); Private window or a profile without a Betfair login; no Air TCP loopback listeners; reviewed release copies only; the Air's staged files only from GitHub at the reviewed merge commit's SHA, never from the lab (section 8.6) | A tampered page can still show anything on screen; Yu's rule is never to type credentials into it. |
| **Same-uid processes, including agents, holding or minting the token** (lab-Claude locally; Nuance through its full-shell key) | Single-use codes; token in memory only and registered with `secret`; `open` and `--print-url` refused over SSH; the agent-conduct rule (agents never run `open`, `ssh-session` or `--print-url`, and never POST commands on a real-data engine); the passphrase-protected viewer key | Not preventable against a determined same-uid process, as in the repo's own threat model (presence.py:1-11). I-8 and I-16 are code-path properties, not proof of a human. The viewer key's forced command, the release copy, the shell startup files and the viewer line in `authorized_keys` (its `from=`, `restrict`, `permitopen` and `command=` options) are same-uid replaceable too. Only the root-owned drop-in's limits (no `-R`, no Unix-socket forwarding, no listeners) are beyond such a process, and the Air self-test confirms the key only at install time (section 8.6). |
| Browser extensions reading licensed data | A Private window, or a profile without extensions | Yu's choice. |
| Supply chain | No third-party Python or JS. A pinned, hash-checked upstream with an import-origin assertion. `-S` drops site-packages. | Homebrew python@3.13 itself. |
| Upstream drift widening imports or changing semantics | The import-closure test, the contract test, reviewed pin bumps | It still blocks work when it breaks, but loudly. |
| Accidental real betting | No live code in this repo, no credential path, FORBID_NETWORK, the audit hook with no off-switch, boundary tests | None in the MVP. |
| Crafted or corrupt data files | Hash of the exact bytes parsed, decompressed size checked against the manifest, tight bounded decompression, the strict reader, `book.py`'s own refusals | — |
| Licensed-data leakage (git, logs, error text, screenshots, model context, browser history, Spotlight, crash reports, SQLite temp files, exports) | Hygiene scanner and pre-commit; synthetic-only fixtures and uisnap screenshots; error mapping; aggregate-only diagnostics; agents never read the ledger or `private/`; `.noindex`; `TMPDIR`/`SQLITE_TMPDIR` and `temp_store=MEMORY`; no-store; exports under `~/betangel-data` only | Human error, covered by review. Analytics and Spotlight Privacy are Yu's decisions (Q-Y14, Q-Y15). |
| Interfering with Nuance's runs | No engine while the run marker exists; no automatic catalogue rebuilds | Until the marker is agreed: conduct only. |
| Agent or scope drift toward live features or automation | The suite's AGENTS.md, the closed route test, the OperatorClick test, synthetic-only `TestOrder`, the proposal process | — |

---

## 10. Safety invariants and how tests prove them

| ID | Invariant | Mechanism | Test |
|---|---|---|---|
| I-1 | No credential code path | Only `rx.py` imports betangel_research, and only from the allowlist | An AST test: `rx.py` is the sole importer, and imports only allowlisted names. A fresh-subprocess import of the full engine checks the closure: the 25 modules, and none of gateway, cli, auth, credentials, transport, api, esa, recorder, killswitch, arming, presence, reconcile, risk or capability. A static scan of **suite sources only** looks for `security` CLI or Keychain strings, Betfair hosts, `placeOrders`, `cancelOrders`, `replaceOrders`, `updateOrders` and `HeartbeatAPING` (the test builds these names by concatenation). The deps closure is checked separately, by its module set and by the absence of gateway order-method literals in those 25 modules. `constants.py:14-32` and `config.py:35` legitimately hold hosts and `"keychain"`. |
| I-2 | FORBID_NETWORK is always on | The launcher sets it. `guard.py` refuses unless `paths.network_forbidden()` is true and no other `BETFAIR*` or `BETANGEL_BETFAIR_*` variable is set. `guard.py` has no off-switch. | Engine start without it is refused. A stray variable is refused. An AST test finds no environment or config read that disables the guard. |
| I-3 | No outbound network, no name lookups | The PEP 578 audit hook (irrevocable), installed before any upstream import, refuses `socket.connect`, `connect_ex`, `sendto`, `getaddrinfo`, `gethostbyname` and `gethostbyaddr`. The one exception: a connect to an absolute, normalised Unix socket path directly in the run dir, permitted before `seal()` with `permit_unix_connect` and matched by its exact text, while the run dir still resolves where it did at `arm()` and the socket path is not itself a link (connect follows one). That is the control socket, which `stop` and the takeovers by `open` and `ssh-session` use (section 9.1). | `socket.create_connection(("192.0.2.1", 443))` (TEST-NET-1) raises before any packet. `getaddrinfo("example.com", 443)` raises. A second hook cannot remove the first. A connect to a Unix path that was not permitted raises, and so does one to a permitted path spelt another way (`run/x/../control.sock`), through a run dir replaced by a link, or to a socket path that is a link. |
| I-4 | Loopback only | The hook allows `socket.bind` only to `("127.0.0.1", port)` and to the control socket path in the 0700 run dir. `getsockname` is asserted. | Binding `0.0.0.0`, the wrong port or another Unix path raises. The server's address is `127.0.0.1`. A control-socket peer of another uid is refused. |
| I-5 | No subprocess after startup | Per guard mode, chosen by the command name only. Before `seal()`:<br>- **engine:** `git -C <abs dir under the suite roots> rev-parse --is-inside-work-tree` (paths.py:149, used by `validate_config` and `StatePaths`) and one `/usr/bin/open http://127.0.0.1:<port>/#c=...`;<br>- **vendor:** its four git argvs (section 3.5);<br>- **release:** local git on this checkout only, with `RELEASE_GIT_PREFIX` and no user or system git config: the filter-driver config query, `ls-files --stage -z`, `status` (never entering a submodule), `rev-parse`, `merge-base --is-ancestor` and `archive` of an object id;<br>- **uisnap:** the exact `swiftc` build argv;<br>- **test:** the test runner never seals. It starts only isolated interpreters (`-I -S -B`), this checkout's `bin/suite`, and local git under `TMPDIR`.<br>After `seal()`, nothing in any mode except uisnap's one binary, registered before `seal()` and started only while its sha256 is unchanged. So `subprocess.Popen`, `os.system`, `os.exec*`, `os.posix_spawn`, `os.spawn*`, `os.fork` and `ctypes.dlopen` are refused. | Startup succeeds. After sealing, `subprocess.run(["/usr/bin/security", ...])` and `os.system` raise. Any other argv during startup raises, in every mode. A uisnap binary that is unregistered, a symlink, or changed after registration is refused. |
| I-6 | Writes confined | The single writer helper, plus the hook's write guard on `open` (write flags), `os.mkdir`, `os.rename`, `os.remove` and `sqlite3.connect` paths: only the suite state roots, plus a temp root in tests. `TMPDIR` and `SQLITE_TMPDIR` point inside the roots as the OS resolves them, links and `link/..` included, and `temp_store=MEMORY` is set. Defence in depth, not a sandbox. | A session over fixtures under a temporary HOME-like root writes nothing outside the roots (tree diff). Nothing appears under `/tmp` or `/var/tmp` during a catalogue build or a session. Writes under a data root, or into a `path_guard` denied tree, raise. |
| I-7 | No live route | The closed route table and command enum | Exact-equality tests and the forbidden-name test. |
| I-8 | Orders on real data come only through the operator-click code path. This is a code-path property, not proof of a human (section 7.1). | OperatorClick minted only in request handlers, with a fresh nonce and a valid session token. `TestOrder` and `ReplayedClick` are accepted only in synthetic mode. | An AST test checks construction sites and the callers of `PaperDesk.place`, `.cancel` and `.withdraw`. Nonce replay places nothing. A `TestOrder` on an engine with a real data root is refused. |
| I-9 | Licensed data never in git | `.gitignore`, the hygiene scanner, the pre-commit hook, the fixture namespace | The scanner fails on planted `.bz2`, a large file and a `1.1xxxxxxxx` id. Fixture-provenance test. |
| I-10 | Raw data read-only; no ingest or index by the engine | A read-only open. The AST test forbids `ingest_archive` and `index_archive(s)` outside tests. | A synthetic data tree's hash is unchanged after a full session. |
| I-11 | No gated month ever replayed | `month_gate` on path and marketTime at catalogue time and at every open. A `None` month is refused as `month_unknown` first. | Synthetic members dated 2026-01, 2026-09, 2026-10 and 2027-01 are refused with the gate reason. A member with no parseable marketTime is refused as `month_unknown`. Research months are refused while no ruling is set. |
| I-12 | Spoiler-free | Catalogue field allowlist; the tap releases outcome values only at their pt | Planted outcome values never reach SQLite, a frame or the browser before CLOSED. |
| I-13 | Pin integrity, and never the moving clone | Per-file hashes, the origin assertion, `sys.path` append only | A tampered file in a temp copy gives `pin_mismatch`. `sys.path` never contains `~/betangel-research`. Origin-assertion test. Oracle tests never pass `~/betangel-research` as `repo_root`. |
| I-14 | Right interpreter | The launcher's absolute path; the version check | 3.15 or below 3.11 is refused. |
| I-15 | Paper fidelity | Exact mode, the yield tracker, position-based re-seeding | The parity contract (section 7.4), the yield-tracker oracle test, the no-look-ahead re-seed test, the full-cancel test, and `journal.verify()` for every session. |
| I-16 | Agents are not handed Yu's token or real rows by the code. This is a code-path property: the code never prints them, but a same-uid agent that disobeys rule 6 is out of reach. | Single-use codes printed only by `open` (to `/usr/bin/open`), `ssh-session` and `--print-url`; token in memory and registered with `secret`; aggregate-only diagnostics; error mapping | Test runs capture stdout and stderr and assert no token or code pattern. A `selfcheck` run over fixtures does not print the fixture's synthetic names or prices. A synthetic member with a bad hash or a truncated line produces no market-id or event-id pattern on stdout, stderr, `logs/` or HTTP. |
| I-17 | No engine during Nuance's runs | The run marker, checked before anything is written under `~/betangel-data` and on every tick | A marker present at start refuses the engine and real-data commands. An unreadable marker refuses them too. A marker appearing mid-session freezes the engine with no writes (tree diff), and it exits within the grace period. |
| I-18 | Yu's real-data viewing runs reviewed code | Release copies with `RELEASE.json`, checked at every launch from a copy; a working checkout runs synthetic mode only. In Phase 0 every engine refuses every data root, from a release copy too. | `serve`, `open` and `ssh-session` from a working checkout refuse a non-synthetic data root. A modified file in a release copy is refused. |
| I-19 | Pause unless watched | Stream-drop, visibility, heartbeat, stdin-EOF and SIGHUP detection, and a 60 s heartbeat timeout; grace and takeover; `max_session_s` for every engine | Dropping the stream, hiding the page, or closing stdin pauses the clock within 2 s. A takeover within the grace period keeps the session. Expiry marks it `abandoned` (the end reason, and `ended reason=abandoned` on the hosting `ssh-session`'s stdout). The fast tier uses tiny graces through the in-process seams; the heavy tier goes through `bin/suite` from a release copy, with the 60 s minimum grace. |

Review of `guard.py`, `rx.py`, `errors.py`, `release.py`, `runmarker.py`, `api/`, the launcher, the boundary tests, the hygiene scanner and pin bumps is routed to Astra (section 3.9; Q-N12 asks about uisnap, the staged viewer scripts, `cli.py` and `roots.py`).

---

## 11. Testing strategy and tooling

- **Python.** stdlib `unittest`, run by `bin/suite test [--py311] [--heavy] [-v] [-k PATTERN] [-j N]` (section 3.6). It discovers tests as this would:
  `cd ~/betangel-suite && env -i ... BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.13 -I -S -B -m unittest discover -s tests -t .`
  It then runs each test module whole in one of N worker interpreters (default 3, at most 4; `-j 1` runs them in the runner itself). `tests/__init__.py` appends the deps clone through `betangel_suite.pin`. It runs on python3.13, and `bin/suite test --py311` runs it again on python3.11.
- **Unguarded children.** The runner's guard refuses every TCP connect and starts only isolated interpreters, this checkout's `bin/suite` and local git. So HTTP test clients run in, and `node` is started by, relay child interpreters (`-I -S -B`) that never import `betangel_suite` and so are unguarded (`tests/test_http_support.py`, `run_relayed` in `tests/__init__.py`).
- **Two tiers.**
  - **Fast** (*measured* about 47-48 s with 3 worker interpreters on the lab M1 under `nice -n 10`, on 3.13 and 3.11; about 61 s with `-j 2`; about 127 s serially): run on every change. It meets the 60 s target only in parallel. Every boundary and security test (I-1..I-8, I-16..I-19, HTTP group 6) stays in it. The default of 3 workers raises peak load on the shared M1, so use `-j 1` or `-j 2` when the lab is busy.
  - **Heavy** (opt-in, `bin/suite test --heavy`; *measured* about 90-95 s in all): in Phase 0, the real uisnap build and WebKit runs, the synthetic size test and the 60 s grace expiry through `bin/suite ssh-session`; later, parity seeds, the 200 random seek points and performance. It refuses while the run marker exists (`run_marker_present`, `run_marker_unreadable`), and it is never run while a Nuance run is announced. The fast tier still runs during a marker (section 6.8; Q-N14).
  - **Pre-commit.** `tools/pre-commit` runs only the hygiene scanner on the staged tree, not the tests.
  - Each run records its runtime (`runtime_s=... python=... tier=... jobs=...`).
  - A run fails with `refused:state_root_changed` if an entry appears or vanishes in the real state root outside `tmp/` while it runs (contents are not compared); only `run/` entries explained by an engine Yu starts or stops meanwhile are exempt (AGENTS.md, Phase 0 status F).
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
  - **Output.** The binary writes no file: it sends PNG and report records on stdout. `uisnap.py` validates them and writes six PNGs of the 1470×830 pt viewport at the display's backing scale (2940×1660 at 2x on the lab, *measured*) and a sanitised `report.json`, which lab-Claude reads. They go by default under `~/.local/state/betangel-suite/uisnap/out/<UTC stamp>/`, or in a missing or empty `--out DIR` inside the suite's write roots. The build is cached under `uisnap/build/` (section 3.7).
  - **What it is for:**
    - in-browser tests that `node:test` cannot run (canvas, DOM, stream handling);
    - layout checks at the Air's Safari viewport (about 1470×830 pt);
    - the seed of the L1 shell.
  - *Measured:* a cold build takes about 40 s, with an explicit clang module cache under `uisnap/build/`, and a WebKit run about 15 s. The design spike also received chunked NDJSON at 100 ms pacing, with no permission prompt.
  - It runs in the lab's logged-in GUI session. The heavy tier runs the real build and WebKit runs in a temporary HOME.
- **CI-free.** No hosted CI. Tests run on the lab, and Nuance can run them on the Air.
- **Fixtures.** `tests/fixtures/gen.py` writes synthetic PRO-shaped streams (reserved ids) with suspensions, images, removals, version changes, 503 windows, in-play and CLOSED. It also writes trd dips for the conservative-parity property, rising trd after a re-seed point, non-finite SP sizes and prices, and markets with no parseable marketTime. Also:
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
     - a click followed by STOP, Esc, Z, X, Shift+Esc or void within 500 ms: the order ends REFUSED with the withdrawal reason and never activates;
     - incremental folder equals `fold()`; `journal.verify()`; the session journal's clock is the `SimClock`;
     - deterministic re-run from `commands.jsonl` (synthetic mode only);
     - V-rule refusals journal nothing (V0, V5, V6, V9 codes included); live-parity refusals; STOP; forward-only and void;
     - writes of `session.json`, `report.json` and a note through the upstream writers.
  5. **Arithmetic** (randomised, integer pence):
     - What-If equals the sum of `order_pnl_pence`;
     - outcomes after greening are equal within 1p, or the green-up is correctly refused;
     - commission is charged only on positive totals;
     - the indicative Rule-4 figure equals `market_realized` where both apply;
     - the exposure oracle agrees on both bases.
  6. **HTTP security:**
     - section 9.2 items 1-9 and the headers, against a real server on an ephemeral loopback port;
     - bootstrap single use and expiry; takeover invalidating the old token;
     - error responses before routing; HTTP/1.1 chunking and keep-alive.
  7. **UI (uisnap):** synthetic screens, keys and stream handling, at the Air viewport.
  8. **Performance** (heavy tier; generous thresholds): synthetic markets sized like the real p50, p99 and max meet the section 6.7 budgets, and RSS stays at 600 MB or less with 2 cached markets.
  9. **Upstream** (heavy tier, on pin bumps only): the upstream offline suite at the pin (section 3.5), plus the contract test.
- **Real-data smoke** (local only; never in git; never while the run marker exists). `bin/suite selfcheck --sample N` opens N random engineering-year members. For each it verifies hashes, replays to CLOSED, and writes a journal containing only notes. It **places no orders**: scripted orders on real data would need a ruling (R-6). It prints **counts and timings only**.
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
| **0: Scaffold, governance, pin, guards and viewing** (lab, synthetic only) | **Governance and pin:** the suite's AGENTS.md, README and this document; `pin/betangel-research.json` and `tools/vendor_research.py`.<br>**Engine and guards:** the launcher (SSH checks before `env -i`); `guard.py`; `rx.py` with error mapping; `roots.py`; `release.py`; `runmarker.py`; the hygiene scanner and pre-commit.<br>**Fixtures:** the synthetic generator, including the synthetic TAR through the vendored ingest and index.<br>**HTTP:** the skeleton (bootstrap code, token, Host, Origin, CSP, closed routes, HTTP/1.1 chunked stream) streaming one synthetic market's best prices.<br>**Viewing:** `ssh-session` with pause-unless-watched, heartbeat and takeover; `bin/suite release`; the staged viewer-key and sshd drop-in script; the Air-side self-test; `tools/uisnap`.<br>**Tests:** I-1..I-14 and I-16..I-19.<br>**Coordination:** the Phase 0 packet to Yu (R-1..R-7, Q-Y8) and to Nuance (Q-N1..Q-N5, Q-N12), and a Collab coordination task. | Tests green on 3.13 and 3.11. The closure is the 25 allowlisted modules. The hook refuses TEST-NET. A tampered pin is refused. Nothing is written outside the roots. uisnap PNGs of the synthetic ladder. **M1: Yu sees a synthetic ladder** on the lab screen, and from the Air if R-2 is approved and installed (*target 2026-10-29*). | Nuance agrees the allowlist, pin, state root and **run marker**. Astra has reviewed the guard, boundaries and launcher. Yu has answered the packet. | 1.5-2 weeks |
| **1a: Data layer, catalogue and read-only replay ladder** | Discovery of indexed roots; head and manifest checks; the spoiler-free catalogue (roles by `market_month`, research months not written); the verified in-memory member reader with the tighter limits; the yield tracker, checkpoints on the new schedule, clock and frames; the SP and definition tap. UI: picker, canvas ladder, one-click grid, countdown, banner, replay controls, chart strip, problem reports. The viewed-markets ledger and `ledger-summary`. Synthetic first. Real-data checks are counts only. | The synthetic UI is complete and accepted through uisnap and Yu's checklist **without PRO**. Real BASIC checks (counts only): the catalogue shows 12,200 engineering-year WIN markets, hides research months and holds no outcome fields; 200 BASIC members pass the reader smoke. Reader and yield-tracker parity pass, as does seek determinism. | Nuance reviews the data path. Yu accepts the synthetic UI. | 2.5-3.5 weeks |
| **M-PRO: first real PRO race** (its own milestone) | Needs Nuance's PRO ingest and index (Q-N4). Ingest and index are single-threaded and read every line of every member: about 100 GB decompressed and about 380M lines, so *inference* about 1.5-3 h of CPU. The run marker covers it. | PRO catalogue built (counts only); open budgets met on real members (p99 ≤ 2 s, max ≤ 8 s); the SP non-finite counts recorded. Yu watches a real PRO race from T-10 to CLOSED at 1-10x, on the lab screen or through the tunnel, from the release copy. | Yu's acceptance. | Dated once Nuance gives an ingest date; about 2-3 days of lab work after that |
| **1b: Paper trading** (after R-1, R-6 and R-7; real-data journal writes only once the run marker is agreed) | PaperDesk with OperatorClick, and `TestOrder` in synthetic mode only; `validate_place`; exact mode with position-based re-seeding; activation, including at CLOSED and at the end of the member; cancel with the correct split, pending withdrawal and keys; STOP; lapse at the off and at close; settle at 2%; positions, exposure on both bases, green-up; the queue tracker; Rule-4 official and indicative figures; journals, `commands.jsonl`, sessions, attempts and void; the live v1 shadow badge; cap profiles; the debrief. With R-7 = ladder trading: exploration mode (replace, drag, size reduction). | The parity contract and conservative property hold; `journal.verify` passes for every session; deterministic synthetic re-run; the arithmetic and exposure property tests pass; the withdrawal and full-cancel tests pass. | Nuance and Astra review the paper path. Yu completes 10 practice races with no confusing refusal or mismatch and confirms the keymap. | 3-4 weeks |
| **1c: Practice log, polish and MVP sign-off** | Practice log and CSV export; sounds; keymap overlay and settings; market overview; exploration mode if not already in 1b; docs (data-handling, keymap, threat model). | No data-hygiene findings in the scanner. MVP tagged. | A week of short sessions by Yu and a written feedback round. Release copy installed. | 1-1.5 weeks |
| **Total to MVP** | | | | **about 8-11 weeks of lab work, plus review waits** |
| **Later L1: native macOS shell** (before any live click) | A SwiftPM executable (AppKit, WKWebView with `WKWebsiteDataStore.nonPersistent()`, `WKURLSchemeHandler` `suite://`), grown from uisnap.<br>**It runs on the Air**, and reaches the lab engine with no forwarding: the forced command `suite ssh-session --stdio` bridges the SSH channel's stdin and stdout to the engine's Unix socket. The viewer key then becomes plain `restrict`, with no port-forwarding.<br>The browser TCP tunnel stays only for the browser MVP.<br>It is built from a reviewed tag, preferably on the Air by Nuance if the Air has the CLT (Q-N13). Otherwise it is built on the lab with CLT Swift 6.3.3 and copied with its hash verified, ad-hoc signed for arm64 (M2). There is no Xcode, Apple ID or distribution.<br>Menu-bar STOP. Global hotkeys need Accessibility or Input Monitoring, which only Yu can grant. | Every MVP feature works with no TCP port open on either machine (`lsof`). A peer from another uid is refused. | Astra's security review; Nuance agrees the Air-side install. | 2.5-4 weeks, including the Air-side install, which depends on Nuance and Q-N13 |
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

Nothing becomes more permissive by configuration alone. **The MVP needs none of these.** R-1..R-7 (section 2.2) are rulings on this repo's design, not rule changes.

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

---

## 15. Open questions

### 15.1 For Yu

**Phase 0 packet (one page):** R-1..R-7 (section 2.2) and Q-Y8. The other questions are deferred to the phase that needs them.

| ID | Question | Needed in |
|---|---|---|
| Q-Y1 | **R-1.** May the suite drive `PaperExchange` directly, outside the gateway, for paper orders you click on historical replay? Nuance asked for your ruling. betangel-research's own batch replay already does this. The alternative imports the credential-bearing gateway. | Phase 0 packet (answered 2026-10-15, section 2.2.1) |
| Q-Y2 | **Viewing (R-2).** Recommended: the forced-command tunnel key plus the sshd drop-in, which you install yourself; lab-Claude stages them. In a Safari Private window, replayed prices appear on the Air's screen and in browser memory only. In a normal window, Safari History and iCloud would also sync the URL and title. Is viewing on the Air fine as personal use? | Phase 0 packet (answered 2026-10-15, section 2.2.1) |
| Q-Y3 | **Commission label (R-3).** You said "Basic 2%". `user_package_verified` on your word, or `user_package_unverified` until you have checked My Account? | Phase 0 packet (answered 2026-10-15, section 2.2.1) |
| Q-Y4 | **State root (R-4).** Is `~/betangel-data/suite.noindex` OK for practice journals, the catalogue and exports? | Phase 0 packet (answered 2026-10-15, section 2.2.1) |
| Q-Y5 | **Practice defaults.** Start at T-10 min; 2x until auto-slow at T-3; pause at the off? One-click on by default, or confirm every order at first? | 1b |
| Q-Y6 | **Practice loss limit** of £20 a day: useful or annoying? | 1b |
| Q-Y7 | **Research-corpus months** (2023-2025): keep them hidden (the default, which protects later research)? Or open them, which needs a ruling id with Nuance and Astra and is logged? | Later |
| Q-Y8 | **Repo workflow.** Lab-Claude pushes branches and opens PRs that Nuance or Astra review (routing in section 3.9). Who merges: you, or lab-Claude after review? May UI-only PRs go on your acceptance alone? | Phase 0 packet (answered 2026-10-15, section 2.2.1) |
| Q-Y9 | **Agents and data.** Confirm that agents never see real rows, the viewed-markets ledger or real-data screenshots, and that any exception needs your OK each time, scoped to one problem report. | 1a |
| Q-Y10 | **Screen Recording: recommended No.** It would be granted to the host terminal (iTerm2) and cover every process under it, and `screencapture` takes the whole display. Any real race on the lab screen would then go into model context, which counts as an upload. `tools/uisnap` gives lab-Claude synthetic screenshots without it. If you still want it, capture would go only through a suite subcommand: that subcommand starts a synthetic-only engine, captures only its own window (`screencapture -l <id>`), and refuses while a real-data engine runs. You would revoke the permission when it is not in use. | Not needed |
| Q-Y11 | **Browser.** A Safari Private window for the suite on both machines (recommended), or a dedicated profile with no Betfair login, no extensions and no iCloud sync? After data downloads, sign out of historicdata.betfair.com in the lab's Safari. | 1a |
| Q-Y12 | **Backups.** Is `~/betangel-data` backed up, for example by Time Machine? Journals and exports are licensed derivatives, so where copies go matters. | 1b |
| Q-Y13 | **Ladder.** Higher odds at the top or the bottom? Keep Bet Angel's keys (Z/X, C)? | 1a |
| Q-Y14 | **Analytics.** Mac Analytics auto-submit is on, so a native crash report from python3.13 or Safari could carry data to Apple. Turn sharing off? This is a privacy setting only you can change. | 1a |
| Q-Y15 | **Spotlight.** Add `~/betangel-data` to Spotlight Privacy? The suite root is already `.noindex`, but the data roots and index JSONL are not. | 1a |
| Q-Y16 | **PRO ingest timing.** The PRO year goes to a separate root and leaves P0's BASIC descriptor untouched. May Nuance ingest it before c2b3b3 lands, if Nuance agrees? | Now (with Q-N4) |
| Q-Y17 | **STOP from a read-only tab** (from the Phase 0c build). As built, a read-only tab cannot STOP: its button is disabled, Q is ignored, and the server answers 409 `not_controller` (section 9.2 item 8). Section 8.2 item 8 says STOP is always reachable by key. `bin/suite stop`, and claiming control first, still work. Should a read-only tab be able to STOP? Allowing it changes an `api/` authorisation rule, so Astra gives a view first (Q-A1). It matters more in Phase 1b, where STOP withdraws pending paper orders. | Before Phase 1b |
| Q-Y18 | **Who makes release copies** (from the Phase 0c build). `bin/suite release <tag>` refuses to run from a release copy, on a dirty tree, or for a tag that local main does not contain, but it cannot tell you from an agent, and rule 6 does not list it. AGENTS.md says making the first release is your decision. Phase 0c's draft of AGENTS.md also said agents never create one; that was left out, because it would be a new rule. Should rule 6 list `release`, or may lab-Claude make a release after review, as it merges PRs? | Before the first release |
| Q-Y19 | **Air-side files in this repo** (Codex review of PR #5). AGENTS.md rule 1 says "No credentials, Betfair API, network or live code ... Later live and Air-side code never lives in this repo"; section 3.9 rule 1 says the same ("Later live and Air code never lives in this repo"). The Air-side sentence speaks of later code, as it does in sections 0, 1.2 and 3.1, while section 8.6 and section 12 have lab-Claude stage two Air-side files for Phase 0: `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`. The real conflict is the unqualified "network code" clause: the self-test is a LAN SSH client, and the snippet configures the Air's end of the SSH tunnel. Options:<br>**(A)** move both to a separate private repo owned by Nuance: rule 1 holds word for word, but the port and Host block are kept in two repos, that repo does not exist yet (Q-N13), and Nuance has to agree to own it.<br>**(B)** keep the Host block only as text in section 8.6 and replace the script with a checklist: no Air code here, but a hand-read checklist loses the script's evidence rule (refused only when the key logged in and the lab refused) and its `ssh -G` preflight.<br>**(C)** a narrow written exception to rule 1's network clause for `tools/stage/air-*`: Yu-run, no credentials, no Betfair API, LAN SSH to the lab with the viewer key only, never run on the lab except under the test fakes. It keeps the tests and one source for the constants, but it is an exception to a binding rule, which rule 10 sends through the proposal process (a `docs/proposals/NNN-<slug>.md`, review by Nuance and Astra, and your written approval).<br>**(D)** you record that the R-2 approval already covered the section 8.6 Air files, and rule 1's network clause is reworded to exclude them: a clarification rather than a widening, because the Air-side sentence covers only later code and the draft you approved already had lab-Claude stage both files (section 8.6), though the recorded R-2 ruling names only the viewer-key script and the drop-in. It still rewords a binding rule, so it may need the same proposal process as C.<br>Lab-Claude recommended C or D, with the Air files taken only from GitHub at the reviewed merge commit's SHA (section 8.6).<br>**Answered: D** (Yu, 2026-10-16: "Go for D"; section 2.2.1). Rule 1's network clause no longer covers the two files (section 3.9, AGENTS.md). Whether D also needs a rule 10 proposal file is not ruled: lab-Claude reads D as a clarification and drafted none (section 2.2.1). | Answered 2026-10-16 (D); whether a proposal file is needed is open |

### 15.2 For Nuance

**Phase 0:** Q-N1..Q-N5, Q-N12, Q-N14 and Q-N15. The others are deferred to the phase that needs them.

| ID | Question | Needed in |
|---|---|---|
| Q-N1 | Do you accept the engine importing only the 25-module closure in section 4.1, with no risk or capability? Will you treat the contract-tested names (section 4.5) as an interface and flag breaking changes in PR descriptions? Is test-only use of `risk` as an oracle acceptable under INTERNAL_ONLY? | Phase 0 |
| Q-N2 | Is the pin by a network-free local clone (`clone --no-checkout --no-hardlinks` from the lab clone, `checkout --detach`, remote removed, read-only) OK? Or do you prefer `git archive`? Who bumps pins? | Phase 0 |
| Q-N3 | **State root and the run marker.** Is `~/betangel-data/suite.noindex` acceptable? Following your A5 answer, the suite will not run at all during your runs. Will your run and ingest wrappers write a marker such as `~/.local/state/lab-runs/ACTIVE`, and wait for `~/.local/state/betangel-suite/run/engine.lock` to be free before touching sources or data? As built, an engine can hold the lock for more than 30 s after the marker appears: the 30 s grace, then up to 0.25 s for the main loop's poll, 1 s for open streams to send their end line and 2 s each for the HTTP and control-socket threads (`server.py` `run` and `_shutdown`), about 35 s, plus any command the actor was already running. Is a wait that long acceptable to your wrapper, in place of the "at most about 30 s" first proposed (section 6.8)? | Phase 0 |
| Q-N4 | **PRO ingest.** When will you ingest and index it (a date), and what is the final data root (`historic-pro`?)? Is it one archive sha, with index v1 built as for BASIC? A header listing shows 12,208 market files at depth 6, all PRO, including 8 in 2016-May (in no contract split). Is there anything in the index the picker should surface? | Now |
| Q-N5 | **Paper semantics.** Is direct `PaperExchange` use with a suite `OrderJournal(path, mode="paper", clock=SimClock)` fine, given Yu's R-1? Intent source `paper_replay` with `customer_strategy_ref` `suite-click` (and `suite-test` in synthetic tests), with click provenance in `note` events, until U-9? Is withdrawing a pending order as SUBMITTING → REFUSED (`operator_withdrawn_before_activation`) acceptable? | Phase 0 |
| Q-N6 | **Quiet-market staleness.** Paper V10 and `_activation_refusal` measure age from the market's last change. Real data shows it is rare near the off. Do you want U-8 at all? (Low priority; the relaxation mode is cut.) | Later |
| Q-N7 | **High-water seeding.** Is it acceptable to rebuild `PaperExchange` with a suite-built `state` whose `traded_hwm` is raised to the raw running maximum up to the replay time (conservative, no look-ahead)? Or would you rather publish U-6? | 1b |
| Q-N8 | Is `config.validate_config` under `StatePaths(home=..., root_override=...)` with FORBID_NETWORK (the test-harness override) an acceptable way to validate the suite's paper config? | 1b |
| Q-N9 | **SP display (R-5).** Do you confirm a suite-side, display-only parser needs no repo ruling? Do you plan U-2, including whether SP non-finites should invalidate the whole book? | 1a |
| Q-N10 | **Rule 4.** Will you take U-1? Until then, is the "indicative, exact-case" figure acceptable? | 1b |
| Q-N11 | **Viewed-markets ledger.** Which fields and format do you want, so markets opened in the suite reconcile with your trial ledger? Agents never read the ledger; reconciliation is by code over salted hashes, printing match counts only. Does human practice on the engineering year matter to P0 or P1? | 1a |
| Q-N12 | **Review routing.** Do you agree the routing in section 3.9 (Astra for guard, rx, errors, release, run marker, api, the launcher, boundaries, scanner and pins; you for data and paper; Yu alone for UI-only PRs)? Phase 0c's review plan also sends uisnap (`uisnap.py`, `tools/uisnap/`), the staged viewer scripts (`tools/stage/`), `cli.py` and `roots.py` to Astra, but AGENTS.md's table does not name them. Should it? That changes which PRs lab-Claude may merge, so Yu rules with you (Q-Y8). Should lab-originated review requests arrive as a lab-journal coordination task plus a mailbox note? | Phase 0 |
| Q-N13 | **The Air later.** Does the Air have the Command Line Tools and Swift? Which Python is there? Will you host the Air-side package (L1/L2) in a separate repo, or in betangel-research, never cloned on the lab? | Later (L1) |
| Q-N14 | **Tests during your runs** (from the Phase 0c build). Under adaptation E (AGENTS.md), `bin/suite test` (the fast tier) still runs while the run marker exists. Since Phase 0c it starts more synthetic engine children (`serve`, `open`, `ssh-session`) in temporary HOMEs, whose marker checks read the temporary HOME's marker path. Rule 7 of section 3.9 says no suite engine runs while the marker exists. Is a fast-tier run during your run acceptable, or should `bin/suite test` refuse then, as `test --heavy`, `uisnap` and `release` already do? | Phase 0 (with Q-N3) |
| Q-N15 | **Rule 1 reword (Q-Y19).** Yu chose option D: rule 1's network clause no longer covers the two R-2 Air files, `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh` (sections 2.2.1 and 3.9). Do you agree with the wording? Option D's text said it may need the rule 10 proposal process, and Yu has not ruled on that; lab-Claude reads D as a clarification and drafted no proposal file. Do you think one is needed? Yu decides. | Before the viewer install (R-2) |

### 15.3 For Astra

**Phase 0 review:** Q-A1 and Q-A2, alongside the review routed in section 3.9.

| ID | Question | Needed in |
|---|---|---|
| Q-A1 | **Read-only tab and STOP** (with Q-Y17). The code follows section 9.2 item 8: `claim_control` is the only command a read-only tab may send, so STOP answers 409 `not_controller` there. Section 8.2 item 8 says STOP is always reachable by key. Would letting a read-only tab send `stop` be acceptable for the API's authorisation rules? Yu rules after your view. | Before Phase 1b |
| Q-A2 | **The scanner's article-number exemption.** `tools/hygiene_scan.py` exempts a 7- or 8-digit help-centre article number from the event-id rule, only in an https `/articles/<n>` or `/<locale>/articles/<n>` URL on four Claude and Anthropic hosts (docs/data-handling.md). Phase 0c narrowed it to that, but no file in the tree uses it yet. Keep it as it is, or drop it until something needs it? | Phase 0c review |

---

## 16. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Review capacity.** Nuance is not starting suite work until c2b3b3 and c2b3b4 are done; each of its tasks needs an Astra round. Lab-Claude carries other workstreams. | Elapsed time set by review latency, not coding. | Lab-done and review-accepted exits; stacked branches; one Phase 0 packet; routing agreed up front; UI-only PRs on Yu's acceptance. |
| **PRO ingest timing.** It has no date yet and comes after c2b3b3. | Real-data milestones slip. | The synthetic UI is accepted without PRO; M-PRO is its own milestone; Q-N4 and Q-Y16 now. |
| paper-v1 is deliberately pessimistic: half of displayed size, no credit for cancellations ahead, unknown queues never fill. Practice may teach that resting orders rarely fill. | Skills and expectations are miscalibrated. | Verbatim assumptions, the queue tracker, fill-quality debrief, the R-7 choice, U-7. |
| About half of races have a non-runner, so there is no official P&L. | Frustration, and pressure for ad hoc fixes. | The exact-case indicative figure, the library filter, U-1. |
| 2015-16 liquidity and behaviour may not transfer to 2026. Replaying a race teaches its result. | False confidence. | "Not execution evidence" labels, attempt counter, forward-only sessions, the spoiler-free picker. More recent PRO months cost £230 each and touch research and holdout rules (Nuance and Astra). |
| Exact mode on big fields lags near the off (about 8x at 44 runners; about 3x in the busiest second). | Slower than requested speed. | Labelled effective speed; prefetch never during exact mode; open budgets by percentile. |
| 8 GB memory pressure shared with Nuance's work and two Claude sessions. | Swapping, interference. | 600 MB target, 1 and 1.5 GB caps, an LRU of 2, `run_paper_replay` banned on real data, nice, no engine during runs, heavy tests opt-in. |
| Upstream drift: the repo moves several times a day; private behaviours are mirrored. | Breakage on pin bumps. | Pin with per-file hashes, contract and parity tests, reviewed bumps, U-3..U-6 to retire the mirrors. |
| R-1, R-6 or R-7 is unresolved, or resolved against. | Phase 1b is blocked or reshaped. | Ask in the Phase 0 packet. The fallback (a gateway with an overridden root) would import credential-bearing modules, so I do not recommend it; it would need restating I-1. |
| Licensed-data leakage through screenshots, model context, error text, Collab, fixtures, browser history, Spotlight, crash reports or exports. | Licence breach. | Agent-conduct rule, error mapping, hygiene scanner, synthetic-only fixtures and uisnap screenshots, Private window, `.noindex`, Q-Y14/Q-Y15, exports under `~/betangel-data`. |
| A same-uid agent uses the UI as if it were Yu. | Paper journals with false provenance. | Single-use codes, in-memory token, SSH-side refusals, the conduct rule; I-8 stated honestly as a code-path property. |
| Lab-served JS in Yu's Air browser is buggy or tampered with. | A fake login prompt; credentials typed toward the lab. | No credential fields ever; Private window; reviewed release copies only; no Air TCP loopback listeners. |
| Localhost attack surface regresses. | CSRF or rebinding against the paper API. | Security tests on every PR. No live endpoint exists to abuse. The SSH-stdio shell before any live click. |
| The viewer key's residual capabilities are misjudged. | A least-privilege gap on a key Yu adds. | The sshd drop-in (no `-R`, no streamlocal); the Air-side self-test; the forced command runs a release copy; Yu can remove the line at any time. |
| An Air disconnect (lid closed, Wi-Fi blip) during a race. | A spent race or a locked-out session. | Pause unless watched; heartbeat; grace and takeover; `ClientAliveInterval` in the drop-in. |
| Lab-Claude cannot see the UI. | Late UI bugs and round trips with Yu. | uisnap from Phase 0; JS logic tests; problem reports and `diagnose` for real-data issues. |
| Real-data-only bugs that agents cannot see. | Slow fixes. | Problem reports (codes only), `diagnose`, the per-incident consent flow, a generator sized like real markets. |
| Scope creep toward live features or automation. | Policy breach. | The suite's AGENTS.md, closed routes, the OperatorClick test, synthetic-only `TestOrder`, the proposal process, the live v1 shadow badge instead of live features, live code kept out of this repo. |
| Later live-key risks: Betfair forbids read-only use of the live key, with no published detection rules. The delayed key also places real bets, and there is no sandbox. | Deactivation of a non-refundable £499 key; accidental real bets. | G1: ask Betfair Developer Support first. Paper never on live-key data; live-key data only in sessions placing real bets. The Heartbeat API is never used (it cancels all LIMIT bets). |
| Toolchain: Homebrew could change python@3.13. 3.15 must stay frozen. There is no Xcode or Apple ID for the shell. | Breakage or certification conflicts. | Absolute interpreter path; the version is recorded in `session.json`; nobody runs `brew upgrade`; CLT-only Swift with ad-hoc signing (verified by uisnap). |

---

## Appendix A. Corrections applied from review (draft 0.1)

Base: the mvp-ux draft. The following were fixed or grafted in:

1. **INTERNAL_ONLY.** The engine no longer imports `risk` or `capability` (tests/test_betfair_boundaries.py:22). Exposure is computed in suite code on both bases, and `risk.worst_case_market_loss` (whose default is `hedge_credit=False`, risk.py:136) is a test oracle only. One `rx.py` facade, enforced by an AST test.
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
