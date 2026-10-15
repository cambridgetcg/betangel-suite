# Proposal 001: Agent seat

| | |
|---|---|
| Status | Draft for review, round 2 (reviewers' fixes applied 2026-10-15). A proposal, not a decision. It adds about one day to Phase 1b (section 7) and otherwise leaves the MVP's scope and dates alone. |
| Date | 2026-10-15 |
| Author | lab-Claude (Claude Code session 03026dfa on the lab MacBook Pro) |
| Reviewers | Nuance (data and paper paths, upstream AGENTS.md), Astra (seat socket, guard, control socket, boundary tests, the bridge) |
| Approver | Yu |
| Base | docs/DESIGN.md draft 0.2 (branch `design/mvp-draft-0.2`, daf9c64) with Yu's rulings R-1..R-7 (section 2.2.1) |
| Process | DESIGN.md section 14; suite AGENTS.md rule 10 |
| Request | Yu, 2026-10-15: an agent seat so agents can trade in the suite, "potentially with models like Jev" (TypeSafe AI's decision model) "and for you [lab-Claude] to use of course". Yu called the agent seat a good idea. |

**Labels.** As in DESIGN.md (*Measured*, *Estimate*, *Inference*), plus *Vendor claim* (the vendor's own statement, not checked), *Secondary* (a third party's report, or a page seen only through someone else's coverage) and *Unknown* (looked for, not settled).

**Names.** Seat kinds are **S1-S4**. Delivery steps are **Step A-F**. Decisions for Yu are **AS-n**.

Sources are in Appendix A (all read 2026-10-15). The research only read public pages. It did not sign up for, contact or send data to any service, and it read nothing under `~/betangel-data`.

---

## 1. Summary and the decision asked of Yu

**The idea.** An agent seat is a second trader using the same replay engine, `PaperExchange` (paper-v1), `validate_place`, cap code and journal format as Yu, in its own sessions. It gets a narrowed, spoiler-free observation and sends typed commands, which go through the same checks as Yu's clicks. In v1 a seat trades **headless only**: no UI, one seat per run, a batch of markets. Trading beside Yu and advising Yu come later (Step F).

**Why a proposal is needed even on synthetic markets.** Three rules stand in the way, deliberately:

1. Suite AGENTS.md rule 3 says "There are no rule-generated orders", with no real-data scope. `TestOrder` was accepted for scripted tests, not strategies. On real data, I-8 and Yu's R-6 also require every paper order to be an `OperatorClick`.
2. betangel-research AGENTS.md:9: "Strategies may generate simulated order intents only within betangel_research/betfair/backtest". It does not separate synthetic from real files.
3. Suite rule 5: "A model context counts as an upload". Betfair's Historical Data terms prohibit "the use of the Historical Betfair Data by, another organization or individual" unless "a specific agreement in writing with Betfair exists".

So a synthetic seat needs AS-3, which amends rule 3 for synthetic mode, and Nuance's answer on AGENTS.md:9 (Q-SN1).

**Recommendation.**

- **Now, in Phase 1b (about one day):** schema seams only: an `actor` field, a per-actor strategy ref, and an order-source type that can later admit an `AgentIntent`.
- **Step A (after MVP sign-off):** a headless seat on synthetic markets. Lab-Claude can drive it from its own shell.
- **Step B:** S1 (agent-written strategy code, run locally) on the free 2015-16 PRO year, after AS-6..AS-11.
- **Step C:** S2 (a local model) only if Yu agrees to install a runtime and weights.
- **Step D:** S3 (Jev) and scripted S4 (Claude via the API) on synthetic markets, only if Yu opens the accounts.
- **Step E:** S3 or S4 on real data only when **Betfair's specific written agreement permitting this use for the named provider is recorded**, and Yu has given the scoped OK in section 5.4.
- **Step F:** a seat beside Yu, and advise mode. **Live** is out of scope (section 6 gives direction only).

**"For you to use", in practice.** Lab-Claude's own seat use stays on synthetic markets until Betfair agrees in writing and an API-key route is approved. Synthetic markets are generated fixtures, so that use is a plumbing test with no trading signal.

**Asked of Yu now:** AS-1..AS-5 (section 8). The rest waits for the step that needs it.

---

## 2. What an agent seat is

### 2.1 The common shape

- **Data mode:** **synthetic** (generated fixtures, reserved ids) or **real** (the indexed PRO engineering year; needs rulings).
- **Control:** v1 is **act** only: the seat's command becomes an `AgentIntent` in the seat's own journal. **Advise** (the seat suggests, Yu accepts) is Step F, with its own ruling (AS-15).
- **Placement:** v1 is **headless** only: no UI, lockstep clock (3.6), one seat per run. The engine is a single flock'd instance, so a headless run and Yu's practice never overlap: Yu's `open` preempts a headless run with STOP semantics (3.5).

### 2.2 Seat kinds at a glance

| | S1 strategy code | S2 local model | S3 hosted decision model (Jev) | S4 Claude |
|---|---|---|---|---|
| Decides | Python an agent wrote, run inside `seat-arm` on the lab | a model on the lab, through an adapter outside this repo | TypeSafe AI's API (US-hosted), through the bridge | scripted: Anthropic's API on an API key, through the bridge. Interactive: lab-Claude through `seat-cli`, synthetic only |
| Licensed-derived data leaving the Mac, on real data | aggregate reports, if agents read them: they enter the authoring agent's hosted context (AS-7) | the same aggregates; the model itself must have no egress | bucketed features at every decision, plus the aggregates | every observation, plus the aggregates |
| Charged latency, in market messages near the off (median about 9 a second, DESIGN 6.7) | about 0-3 (a declared 250 ms) | about 30-90 (3-10 s, *inference*) | about 2-4 (about 0.1 s model time, *secondary*, plus 70-150 ms UK-US, typical values) | about 10-140 (1-15 s, *secondary*; to be measured) |
| What limits its cadence | CPU only | memory and latency | rate limits, spend, Jev's weak numbers | spend, latency, rate limits |
| Licence exposure on real data | low, not none | low, not none | high: another organisation processes derivatives | high |
| Rulings needed for real data | AS-6..AS-11 | plus AS-12 | AS-13(b) and Betfair's agreement naming TypeSafe | AS-14(b) and Betfair's agreement naming Anthropic |

Every seat order also pays paper-v1's 500 ms submit latency (about 4-5 messages), as Yu's clicks do. In lockstep, decision latency only moves the moment a command lands, so it never makes fills better (3.6). Per-tick work (scalping, queue jockeying) is out for every seat because of that 500 ms, and for S3 also because Jev handles numbers badly. Model speed alone does not set the cadence.

### 2.3 S1: strategy code

- **What.** An agent writes a strategy module: one function from `seat-obs-v1` to `seat-cmd-v1`, which must pass an AST allowlist (3.1). It is written and tested on synthetic markets. On real data it runs only in a batch Yu has armed, loaded by a code hash Yu armed.
- **Where the code lives.** Strategies written and tested only on synthetic markets may go in git. A strategy changed after any real-data run has been tuned on licensed-data feedback. It stays under the suite root (`strategies/`), never in git, until Betfair answers 5.3(b) or Yu rules otherwise (AS-10). The hygiene scanner cannot detect fitted thresholds.
- **What the author sees.** Only what AS-7 allows. Jev or another model may help write code from synthetic results only. No report from a real-data run goes to Jev, or to any agent not named in Yu's OK.
- **Good for.** Execution plans (enter, wait, green, cancel), turning Yu's written plan into code, testing the harness, and running hundreds of markets headless.
- **Risks.** Overfitting through fast iteration (4.4). Covert channels: a strategy author can encode observed values in stake or price choices that surface in fills or P&L. AS-7's limits reduce this, but the protection rests on rule 5 conduct, as I-8 does.
- **Belongs in the backtester instead** when the question is about an edge (4.6).

### 2.4 S2: local model

- **What.** A small model on the lab chooses among enumerated actions from `seat-obs-v1`. It runs behind an adapter outside this repo that connects to `run/seat.sock` as a client, so no guarded process connects to the model runtime (3.1). The adapter follows the bridge rules (3.9), and its lack of egress must be shown, not assumed.
- **Candidates (*secondary*).** Gemma 4 E2B or E4B (about 4 GB, or 5.5-6 GB, at 4-bit, Apache-2.0); Qwen3-4B (MLX 4-bit); Cloudflare's Clef-flash (9B, Apache-2.0 open weights, reportedly speaking Jev's SystemOne wire format; whether it fits in 8 GB beside the engine is *unknown*).
- **Latency.** On a base M1, llama.cpp runs a 7B model at Q4 at about 110 tok/s for prompts and 14 tok/s for generation (*secondary*): about 17 s just to read 2k tokens. A 2-4B model at 4-bit takes about 3-10 s per cold decision (*inference*).
- **Risks.** Weak at numeric ladder reasoning. Memory: the engine targets 600 MB, Safari takes about 220 MB, and Claude Code and Nuance's runs share the same 8 GB. Installing is new software (lab rule 6, AS-12). Caches and logs must stay under the suite root.

### 2.5 S3: hosted decision model (Jev)

- **What it is.** TypeSafe AI's "System One" model, "in early access" (*vendor claim*). It takes a state plus typed questions and returns typed answers with probabilities: `noul` (yes or no), `choice` (up to 255 options) and `score` (2-10 ordered levels). Versions: `jev-1.13.0` (2026-09-15) and `jev-1.14.0` (preview, 2026-10-14). The `jev-latest` alias is due to move to 1.14 "in a week".
- **Price (*vendor claim*).** $0.042 per million input tokens; output is free. The launch post says the team "can't prove it isn't subsidized". At 1-2k tokens a decision costs about $0.00004-0.00008 (arithmetic).
- **Latency.** *Vendor claim:* 70-500 ms end to end. Vals AI measured a median of 0.10 s from one residential machine, no p95 (*secondary*). No SLA or p95/p99 is published. The Privacy Policy says "The Services are hosted in the United States", so the UK round trip adds very roughly 70-150 ms plus TLS (typical values, not measured).
- **Fit.** In lockstep, that latency costs about 2-4 messages, less than the 500 ms paper latency. The real limits are rate limits (Vercel Gateway users reported 429 shedding from about 2026-09-26, often one accepted call every ~300 s, *secondary*), spend, and Jev's weak handling of numbers. Decisions every 5-30 s, or choosing runners and markets, fit. Per-tick work does not.
- **Strengths and limits.** TypeSafe's own "jaggedness" page says "Jev is not a calculator": it counts unreliably, handles numbers and dates badly, and leans toward the first-listed choice. Independent calibration is mixed (*secondary*): Vals found an ECE of 0.011 on one task and 0.108 on another; an out-of-distribution test found 0.107; probabilities are rounded to 0.01. A ladder is mostly numbers, Jev's probabilities measure fit to a rubric rather than P(win), and the market price already prices win probability. Realistic uses (*inference*): applying Yu's written rubric consistently, parsing typed operator commands, and checking another seat's proposed action against Yu's plan.
- **Terms.** No region choice is documented; zero data retention is enterprise only. MCA §4.1 and §4.3 let TypeSafe derive "Telemetry", including "hashes, summary statistics and classifications", and process it "without restriction"; §10.3 allows data to stay in backups. MCA §5 makes the customer warrant rights over the input. §2.3(b) bans using output to "train a model to imitate the output". The Acceptable Use Policy does not mention gambling or trading. The site Terms say the Site "is intended for visitors located within the United States". New signups were paused on 2026-09-22 (*secondary*); today's status is *unknown*.
- **Access needs.** A TypeSafe account and an API key, which is a new secret on the lab (lab rule 6, AS-13), and the bridge outside this repo (3.9).

### 2.6 S4: Claude

- **Two routes, kept apart.**
  - **Interactive, synthetic only.** Lab-Claude, in a session Yu started, runs `bin/suite seat-cli observe` and `seat-cli send` from its shell. This needs no config change and no MCP registration. Lockstep charges lab-Claude's real thinking time. `seat-cli` refuses a real-data engine in code.
  - **Scripted (synthetic first; real data only under AS-14(b)).** The bridge makes one stateless Messages API call per decision, on an Anthropic API key under the Commercial Terms. It uses strict tool schemas and reads `usage` from each response. It never goes through Claude Code, for two reasons. The Consumer Terms bar access "through automated or non-human means, whether through a bot, script, or otherwise" "Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it". And a Claude Code loop adds its own system prompt and a growing context, and leaves transcripts, auto-memory, file history and MCP tool output outside `~/betangel-data`. (*Inference:* headless `claude -p` on Yu's subscription may be permitted for personal use; this proposal takes the conservative route.)
- **Lab-Claude today.** It runs on Yu's consumer Max login. Retention is 30 days, or 5 years if "help improve Claude" is on. Zero data retention is not available on consumer plans. Transcripts sit in plaintext under `~/.claude/projects` for 30 days by default.
- **On the API (if AS-14).** "Anthropic may not train models on Customer Content from Services". Inputs are deleted within 30 days (privacy article) or not retained by default (API docs); treat 30 days as the upper bound. Flagged content is kept up to 2 years, even under ZDR, and ZDR comes only through sales. Batch (29-day retention), the Files API, the MCP connector and Covered Models (Fable 5/5.1 and Mythos 5/5.1, which require 30-day retention) are not used.
- **Latency (*secondary*: Artificial Analysis P50, US-side, 10k-token input, low effort).** Sonnet 5.5: 1.17 s to first token, 6.23 s for 500 output tokens. Haiku 5.5: 7.69 s. Opus 5.5: 9.05 s. Sonnet 5.5 and Haiku 5.5 can also run with thinking off, and Haiku 4.5 non-reasoning showed 0.50 s. All are to be measured from the lab with 1-2k-token prompts.
- **Cost.** At list prices, 2k input and 200 output tokens with thinking off cost about $0.0003 on Haiku 5.5, $0.006 on Sonnet 5.5 and $0.012 on Opus 5.5 per decision (arithmetic). One decision every 5 s for 10 minutes is about $0.75 a race on Sonnet, and about $9,000 for the whole year. Hence spend caps and small samples. The interactive route costs no API money, but it draws on the Max usage allowance that lab-Claude's build work also uses, so it is budgeted in markets per day.
- **Risks.** Memorised 2015-16 results: anonymisation only partly removes memorisation (*secondary*). Outputs cannot be reproduced, because Claude 4.7 and later reject a non-default temperature. The licence (section 5).

---

## 3. Interfaces

### 3.1 Processes, sockets and the guard

```
 engine: bin/suite serve, headless run started over the control socket
   guard as today, plus one pre-seal bind permit for run/seat.sock
   actor thread -> PaperDesk -> PaperExchange + journal for the seat's session
   observation builder (3.2), decision scheduler and lockstep clock (3.6)
   run/seat.sock (0600, 0700 run dir, same uid via getpeereid, one connection per token)
        ^                           ^                             ^
 seat-arm (S1 host)           seat-cli                     bridge or S2 adapter
 release copy, run by Yu      synthetic only               outside this repo, unguarded,
 guarded: connect only to     guarded: connect only to     bridge rules (3.9) -> one API host,
 seat.sock; read-deny         seat.sock                    or the local model runtime
```

- **The human path is untouched.** The HTTP route table and command enum are unchanged (I-7), and a headless run has no UI.
- **Out of process.** Strategy code inside the engine could reach the decompressed member, which holds future messages, through `gc`. A separate process gets only what the socket gives it, plus whatever it can read from disk. The guard change below addresses the disk.
- **Guard changes (3.8, routed to Astra).**
  - Engine: a pre-seal bind permit for `run/seat.sock`, beside the control socket (I-4).
  - `seat-arm` and `seat-cli`: a pre-seal `AF_UNIX` connect permit for exactly that path. Every other connect stays refused (I-3), including other Unix paths: the control socket, the bridge, Collab, a llama-server socket.
  - `seat-arm`: once the strategy is loaded, refuse read opens, `listdir`, `scandir` and `stat` under `~/betangel-data`, the suite state roots and the deps clone. `guard.py` today audits only writes (I-6), so without this a strategy could read PRO members, the catalogue or journals.
  - This is defence in depth, not a sandbox. Same-uid code that escapes the audit hook is out of reach (DESIGN 9.4).
- **Strategy AST allowlist (I-20).** Imports only from a short list (for example `math`). No `open`, `print`, `eval`, `exec`, `compile`, `__import__`, `getattr`, `os` or `sys`, and no dunder names or attributes.
- **Egress lives outside this repo**, in the bridge (S3, scripted S4) or the S2 adapter. For those kinds the bridge, not `guard.py`, is the egress boundary.

**Arming and tokens.**

- **Synthetic engine.** Agents may arm: `bin/suite seat-arm --synthetic` writes the token to a 0600 file in the run dir for `seat-cli` or the bridge.
- **Real-data engine.** Only Yu arms, with `bin/suite seat-arm` from the release copy at the lab's terminal. It reads a typed line at `/dev/tty`, then asks the engine over the control socket (new verb `seat_arm`) for a headless run with this manifest: seat kind, strategy-hash allowlist, sample seed, size and filters, budgets, expiry and ruling id. Yu sets these; agents and strategies do not.
  - For S1, `seat-arm` itself is the seat host. It loads the strategy by an armed hash, applies the read-deny, connects to `seat.sock` and keeps the token in memory. No token is ever written to disk on a real-data engine.
  - The engine binds the token to the armed kind and picks the observation profile from that kind, never from what a client declares. A second connection with the same token is refused. A kind not in `SEAT_REAL_DATA_KINDS` (a reviewed code constant, empty today) is refused on a real-data engine.
  - S2 and S3 on real data would need the adapter or bridge to get its token without a file on disk. That is open (Q-SA1), and neither step is near.
- **The `/dev/tty` step is friction, not a barrier.** *Measured* 2026-10-15: lab-Claude's plain shell cannot open `/dev/tty` ("Device not configured"), but under `/usr/bin/script` it can, and `ssh -tt` with the Air's full-shell key would allocate a terminal too. The engine also cannot tell how an arm message on the same-uid control socket was produced. So arming rests on the conduct rule (rule 6) alone. `session.json` records the arming channel. Yu arms from the lab's own keyboard, or from a full-shell terminal session from the Air. The R-2 viewer key gives no terminal, so it cannot arm.

### 3.2 Observation: `seat-obs-v1`

- **How it is built.** From the same materialised snapshot that click validation uses (DESIGN 6.2), at replay time V, from messages with pt ≤ V only. Integers and closed codes only.
- **When.** From the start of the seat window (T-10 min by default) until the in-play flip, never after. V9 refuses in-play orders and LAPSE orders lapse at the flip, so a seat has nothing to do in-play. The engine replays on to CLOSED and settles for the reports. The seat never receives in-play data or any settled total.

| Group | Fields |
|---|---|
| Header | `obs_seq`, `obs_sha256`, `profile` |
| Clock | `ms_to_off` (signed, to the first-published scheduled off), `market_status` code, `book_age_ms`, `invalid_reason` code |
| Market | `n_active`, `n_removed_so_far`, `overround_bp`, `bet_delay_s` |
| Runners, by handle `R1..Rn` | status code, `ltp_h`, best 3 back and lay `{price_h, size_p}`, `traded_p` (PRO ÷2 basis, DESIGN 6.5), LTP move in ticks over 30 s and 120 s, traded per minute over the last 120 s; `full-v1` adds a ±N-tick ladder window |
| Own state | orders `{order_handle, runner, side, price_h, size_p, matched_p, remaining_p, state, queue_ahead_p or null}`, if-win P&L per runner, green value gross and net of 2%, exposure on both bases (DESIGN 7.7) |
| Limits | headroom on stake, liability, market, total and loss; orders left this minute (pt axis) and this race; decisions left |

- **Never in an observation:**
  - market, event or selection ids, venue, event or runner names, `sortPriority`;
  - dates or wall-clock times, the member path, size or time span, and the attempt count;
  - `evaluator_only_outcome`, `coverage`, `provenance.other_sources`, `view_ends.reason`;
  - projected SP and the final `bsp`. R-5 approved the SP tap as display only, "never passed to `validate` or `PaperExchange`", and feeding it to automated decisions would widen R-5 (Q-SN7);
  - WINNER or LOSER, and settled totals.
- **Handles.** `R1..Rn` come from a salted shuffle per session (the salt stays under the suite root), so their order reveals neither `sortPriority` nor the cloth number.
- **Profiles.**
  - **`full-v1`** (S1, S2): the integers above.
  - **`bucketed-v1`** (S3, S4): categories computed in code, with no exact prices or volumes: time-to-off and field-size buckets; price rank and odds band; spread in ticks (1, 2-3, 4+); weight-of-money class over the top three levels; depth at best; LTP move over 30 s and 2 min; traded rate against the market's own history; volatility and overround bands; own position and the green P&L sign and band; unmatched-order age and queue-ahead buckets; cap headroom.
  - **Cut points are fixed a priori in code**, from tick bands, ladder structure and the observation's own prefix. None is fitted on real data. "The market's own history" means messages with pt ≤ V only. The definition is hashed (`bucketed-v1` schema sha256), and the hash goes into Yu's OK.
  - `bucketed-v1` and its leak tests (Q-SA5) are built in Step D, so Step E is a reviewed flag flip.
  - **Bucketing does not make data unlicensed.** Buckets are still derivatives (section 5).
- **Synthetic generators** used for seat sessions take only parameters already published in DESIGN (counts and sizes). They are never fitted to real price or volume paths without a ruling from Yu. Otherwise "synthetic" observations sent to Jev or Anthropic would become licensed derivatives.

### 3.3 Command: `seat-cmd-v1`

Every command is `{seat_id, nonce, obs_seq, cmd, reason}` plus the exact keys its `cmd` needs. It is parsed with `receipts.strict_json_loads` against an exact-key schema per `cmd`, integers only. `obs_seq` must be the latest observation issued to this seat; otherwise it is refused as `seat_stale_observation`.

| `cmd` | Extra keys | Effect |
|---|---|---|
| `place` | `runner`, `side`, `price_h`, `size_p` | One LIMIT/LAPSE order. The handle maps to `selection_id` inside the engine, then exactly the click path of DESIGN 7.3: `validate_place(..., mode="paper")`, journal, activation 500 ms after T_submit. |
| `cancel` | `order_handle` | That order, whole bet. A pending order is withdrawn (DESIGN 7.6). |
| `cancel_all` | — | Every order of this seat in the market. |
| `green_up` | `runner` | The engine computes the hedge (DESIGN 7.8) and places it as one `place`, with the same checks. |
| `pass` | — | Nothing; journalled. |
| `seat_stop` | — | The seat halts itself: cancel all, then refuse further commands. |

- **`reason`** is a closed code (for example `entry`, `exit`, `green`, `risk`, `none`), never free text.
- **Not in the seat enum:** `resume`, `claim_control`, `open_market`, `seek`, `jump`, `set_speed`, `void_and_rewind`, `replace`, `export_csv`, `report_problem`. The forbidden-name test (`live`, `account`, `funds`, `login`, `kill`, `upload`, `share`) covers this enum.
- **Engine-side triggers** (brackets, stops, offsets) are not in v1. They are P-1 automation (DESIGN 14).
- **Refusals** are closed codes: the V-codes plus `seat_*` codes.
- **Model output.** The bridge uses strict tool schemas (Claude) or typed SystemOne questions (Jev). That guarantees the shape only; the engine's validation is the boundary.
- **Output hygiene.** `seat-arm`, `seat-cli` and the bridge print codes only. Strategy stdout, stderr and exceptions are mapped to closed codes, as in DESIGN 9.2 item 9. Full tracebacks go over the socket to the engine, which writes them to `private/`.
- **Decision envelope.** The client sends it over the socket with each command, and only the engine writes it, to the seat log under the suite root. It holds `backend` and a pinned `model_id` (for example `jev-1.13.0`, never `jev-latest`), `effort`, `obs_sha256`, `cmd`, the validation code, `latency_ms`, tokens in and out, `cost_microusd`, and any returned probabilities. No prompt text is kept for real-data observations.

### 3.4 Actor and journals

- **The actor** is `operator`, `agent:<seat-id>`, `engine:<seat-id>` or `test`. A seat id matches `s[1-4]-[a-z0-9]{1,8}`. It is recorded on every `commands.jsonl` line, in `session.json` (with kind, backend, model id, profile, ruling id and arming channel), in the provenance `note` after every intent, and on every viewed-markets ledger row.
- **In the intent itself** it appears only through `customer_strategy_ref` (`ag-<seat-id>`, within `[A-Za-z0-9-]{1,15}`, journal.py:210), because `INTENT_PAYLOAD_KEYS` is an exact set (journal.py:95-96). The intent `source` stays `paper_replay` (journal.py:97) until Nuance adds U-9 (human paper) and the proposed **U-10** (`agent_paper`).
- **One session, journal and `PaperExchange` per (market attempt, seat).** A v1 run has one seat and no operator, so `PaperDesk` needs no shared book between actors until Step F.
- **`AgentIntent` is a separate type.** No code path converts it to or from an `OperatorClick`.
- **Engine actions for a seat** (watchdog cancels, budget refusals, timeouts turned into `pass`) are written to `commands.jsonl` with actor `engine:<seat-id>` and their pt, so re-runs reproduce them (3.7).

### 3.5 Budgets and STOP

| Control | Proposed default | On reaching it |
|---|---|---|
| Cap profile | `v1-live-mirror`: £2 stake, £10 liability, £20 market, £50 total, 6 orders/min (pt axis), 10 ticks from best | that order is refused (V-codes) |
| Orders per race | 10 | `place` refused; `cancel`, `cancel_all`, `green_up` (within caps) and `pass` still accepted |
| Decisions per race | scheduled points (600/K + 4 marks) plus 50% for event triggers; K = 5 s gives 186 | only the T-2 and T-1 observations are still issued, accepting `cancel`, `cancel_all`, `green_up` and `pass` |
| Loss limit | £20 per historical race-day within a run | the seat halts |
| API spend | USD per run and per day, from each response's `usage` via the envelopes; the vendor's console limit as a backstop | the seat halts |
| Interactive S4 | markets per day (it draws on the Max allowance) | no new market |
| Run size and wall time | at most 400 markets for S1 (about 30 s of CPU each, so about 3.5 h); 4 h wall cap | markets not reached are reported as `seat_not_run_wall_cap` |
| Runs | per day, set by Yu at arming | no new run |
| Decision timeout | 1 s for S3, 30 s for scripted S4, then `pass` | 3 in a row halt the seat |

- **Halt-and-cancel** is kept for STOP, the watchdog, the loss limit and spend breaches: pending orders are withdrawn, executable ones cancelled (DESIGN 7.6), and `halt {reason}` is journalled. Matched positions stay and settle. Running out of orders or decisions only refuses new `place`, and unmatched orders lapse at the off as usual.
- **STOP beats the agent.** Yu's STOP (`bin/suite stop` or `run/STOP`) ends a headless run. Seats cannot resume. `bin/suite seat-stop <id>` (control-socket verb `seat_stop`) stops one seat; agents may run it, as rule 6 already allows `stop`.
- **Yu comes first.** Yu's `open` preempts a headless run with STOP semantics. Its remaining markets are reported as `seat_not_run_preempted`.
- **Watchdog.** If no decision arrives within the timeout while the seat has orders, all its orders are cancelled.
- **Fail closed.** A timeout, a 429 or 529, a schema failure or a refusal means `pass`. Nothing ever retries on an older observation.
- **Nuance's runs.** Only the engine writes under `~/betangel-data`. `seat-arm`, `seat-cli`, the bridge and the S2 adapter write nothing there; they send envelopes over the socket. When the run marker appears, the engine freezes (DESIGN 6.8) and closes `seat.sock`. Clients exit on the closed socket, and the bridge also checks the marker before every call (I-17 extended).

### 3.6 Clock and latency charging

- **Lockstep**, for every v1 seat:
  1. At a decision point the engine pauses at V, issues an observation, and waits.
  2. On the reply, T_submit = V + the charged latency: the measured wall-clock round trip for S2-S4 and `seat-cli`, or a declared 250 ms for S1 (*inference*).
  3. The engine replays forward to T_submit and validates against the book there.
  4. The 500 ms paper submit latency then applies (DESIGN 7.3).
- **Decision points:** T-10, T-5, T-2 and T-1 minutes; every K s of replay time (K ≥ 1 for S1, ≥ 5 for S3, ≥ 10 for S4, set at arming); on the seat's own fills; and on an LTP move of N ticks or more.
  - The next observation is issued at the first decision point after T_submit, so none overlaps a pending command.
  - Triggers inside the latency window coalesce into one. Skipped points are logged as `seat_decision_skipped_latency`.
- **Uncharged mode** (T_submit = V) is for debugging only. Its reports say "uncharged latency: training only" and are never counted.
- **Headless runs are not "watched".** I-19 (pause unless watched) is scoped to UI sessions; a headless run is bounded by its wall cap.
- **Market order.** A run samples markets with Yu's seed, then replays them in strict chronological order of first-published marketTime. No market is offered to the same seat twice. With no in-play data and no settled totals, a stateful strategy can learn only from earlier races' pre-off data.
- **Throughput (*estimate*).** An exact step costs about 5 ms at the median (DESIGN 6.3), and a median market has about 5,400 messages in its last 10 minutes. With orders open throughout, that is about 30 s of CPU per market: about 3.5 h for 400 markets, and about 100 h for the full year.

### 3.7 Deterministic re-run

- A re-run feeds the logged seat commands and `engine:<seat-id>` actions, at their logged pt, through `PaperExchange`. It never queries the model again.
- **Synthetic:** always available; a test asserts an identical fold. The `run_paper_replay` parity export (`submit_pt = T_submit`) applies only to place-only S1 sessions. Sessions with cancels or withdrawals are "parity not checkable" (DESIGN 7.4).
- **Real data:** R-6 forbids re-executing orders there today. Headless re-runs with AS-7 output come with AS-11.

### 3.8 Rule changes this proposal needs, and what stays

Each row takes effect only through the AS item in its last column. AS-1 adopts no rule text.

| Rule | Today | Proposed | Through |
|---|---|---|---|
| Rule 3, synthetic | "There are no rule-generated orders"; `TestOrder` (scripted tests) in synthetic mode only | Add: "In synthetic mode an armed agent seat may send `AgentIntent` paper orders, consumed only by `PaperExchange`." | AS-3 |
| Rule 3, real data | Every paper order on real data is an `OperatorClick` | "...or an `AgentIntent` from a seat Yu armed for that run, of a kind in `SEAT_REAL_DATA_KINDS`, under a ruling id recorded in `session.json`. Agent intents are consumed only by `PaperExchange`. There are no other rule-generated orders." | AS-6 |
| Rule 5 | A model context counts as an upload | Add: "A seat observation is a model context. Agents never read real-data seat observations, seat logs, seat session folders, decision envelopes or seat-host output; `bin/suite seat-report` is the only reader and prints only what AS-7 allows. S3 and S4 seats receive real-data observations only under a ruling id whose scope (provider, endpoint, pinned model, observation-profile hash, spend cap, end date) is recorded, and only when Betfair's specific written agreement permitting this use for the named provider is recorded." | AS-6, AS-7; the S3/S4 clause with AS-13(b), AS-14(b) |
| Rule 6 | Commands agents never run | Add: "On an engine with real data roots, agents never run `seat-arm`, `seat-cli` or a bridge, never connect to `run/seat.sock`, and never read seat tokens. Yu starts real-data seat runs. Agents may run `seat-stop`." | AS-6 |
| I-3, I-4 (guard) | Every connect refused; binds only to 127.0.0.1:port and the control socket | Engine also binds `run/seat.sock`; `seat-arm` and `seat-cli` may connect to exactly that path; `seat-arm` read-deny after strategy load (3.1) | AS-3 (Astra) |
| Control socket (DESIGN 9.1) | `attach`, `new_code`, `pause`, `stop` | Add `seat_arm` (which starts a headless run) and `seat_stop`; the verb test changes | AS-3 (Astra) |
| I-8 | Orders on real data come only through the operator-click path | "...or the armed-seat path. `AgentIntent` is minted only in the seat-socket handler for an armed seat. Neither converts into the other." | AS-3 (synthetic), AS-6 (real) |
| I-16 | Agents are not handed Yu's token or real rows by the code | Add: "`seat-arm`, `seat-cli` and `seat-report` print codes and AS-7 aggregates only. The seat socket hands real-data observations only to one connection holding a token bound to an armed kind in `SEAT_REAL_DATA_KINDS`." | AS-6 |
| I-19 | Pause unless watched | Scoped to UI sessions; headless runs are bounded by the wall cap | AS-3 |
| R-6 (Yu) | No rule-generated paper orders in the MVP | MVP unchanged. After the MVP, superseded by AS-6 and AS-11. | AS-6 |
| betangel-research AGENTS.md:9 (Nuance) | Simulated intents only inside `betfair/backtest` | Nuance to answer or draft: suite seats consumed only by `PaperExchange`, on synthetic files (Q-SN1), and later on local historical files | AS-3, AS-6 |

`SEAT_REAL_DATA_KINDS = frozenset()` sits in `betangel_suite/seat/policy.py`, following the `STATE_ROOT_AGREED` pattern, so nothing becomes more permissive by configuration alone. Advise mode and beside-Yu placement need further rows (a `place` body key, frame fields, a UI stop control); they are Step F's, not v1's.

**New invariants:**

| ID | Invariant | Test |
|---|---|---|
| I-20 | Seat isolation | The HTTP route-table and enum tests are unchanged. An AST test finds `AgentIntent(` only in the seat-socket handler and `OperatorClick(` sites unchanged. An unarmed or stopped seat is refused; a second connection with the same token is refused; the profile follows the armed kind. Strategy modules pass the AST allowlist. |
| I-21 | Observations are spoiler-free, identifier-free and pre-off only | Planted outcomes and identifiers never appear in an observation. Prefix invariance: cut the member at t, or alter later BSP, results, removals and definitions, and every observation at or before t is identical. No observation after the in-play flip, and no settled total. A planted stateful strategy across a run sees no outcome or in-play data. |
| I-22 | STOP beats seats | STOP ends a headless run; the seat enum has no `resume`; Yu's `open` preempts; watchdog test. |
| I-23 | Still no network in this repo | `seat-arm` and `seat-cli` run under the guard. Every connect other than the `seat.sock` path raises: TEST-NET and other Unix paths (control socket, Collab, a llama-server path). A planted strategy that tries to read a synthetic member, the catalogue or a journal is refused. |
| I-24 | Budgets hold | Each counter refuses at its limit. Order and decision budgets refuse only `place`; loss and spend breaches halt. A run marker mid-run means no writes by any seat process (tree diff, I-17). |

- **Tests that change.** The `OperatorClick` AST test gains the `AgentIntent` site. The forbidden-name test covers the seat enum. The I-3/I-4 tests gain the `seat.sock` permits. The control-socket verb test gains two verbs.
- **Safeguards kept.** All of DESIGN section 10: no live code, no credentials, paper only, licensed data under `~/betangel-data`.
- **Evidence required before any real-data seat.** I-20..I-24 green on synthetic markets. Measured p50 and p95 latency per backend from the lab on synthetic payloads (Jev; Sonnet 5.5 and Haiku 5.5 with thinking off and at low effort). A STOP demonstration that Yu has watched. For S3 and S4, Betfair's specific written agreement for the named provider.
- **Rollback.** Immediately: Yu stops arming, and STOP or `seat-stop` ends what runs. In code: `SEAT_REAL_DATA_KINDS` back to empty, which takes effect only with `bin/suite release <tag>`, because real-data engines run the release copy (I-18); `seat-arm` checks the constant in the running release. The AGENTS.md text reverts (Nuance upstream). Seat sessions stay readable and labelled.

### 3.9 The bridge and the S2 adapter (outside this repo)

- They live in a separate repo or folder outside the suite (Q-SA3), are reviewed under Astra's routing, and fall under suite rule 5.
- **Egress to exactly one host:** `api.typesafe.ai` (S3) or `api.anthropic.com` (S4). No gateway or reseller (Vercel, OpenRouter, Runware). The S2 adapter has no egress at all, shown by test.
- **TypeSafe SDK settings:** `max_retries=0`, a timeout of 1 s or less, log level WARNING or above with body logging off (at `debug` the SDK logs request and response bodies unredacted), Jev 1.14's opt-in to share queries with TypeSafe left off, and a pinned model id. **Anthropic:** strict tools, no retries, a 30 s timeout, none of Batch, Files, the MCP connector or Covered Models.
- **Logs** carry codes only, never request or response bodies. Nothing is written under `~/betangel-data`; envelopes and usage go over the socket.
- **Checks:** a static scan for Betfair hosts and order-method names (the I-1 list); the run marker checked before every call; a real-data engine refused unless the engine's handshake shows a kind armed for real data.

---

## 4. Evaluation hygiene

### 4.1 Spoiler-free observations, and leaks through features

- Observations use the prefix only, stop at the in-play flip, and never carry settled totals (3.2, I-21). The definition tap releases nothing early (I-12).
- Outcome-correlated fields are excluded by allowlist, not by blocklist.
- Charged latency prevents optimistic fills (3.6).
- **Memorisation.** A hosted model shown a venue, date or runner could recall a public 2015-16 result. Removing identifiers closes the obvious route. Whether price patterns alone let a model recognise a race is *unknown*; anonymisation only partly removes memorisation (*secondary*). Hosted results are labelled and never evidence.

### 4.2 Data roles

| Split | Months | Seats |
|---|---|---|
| Engineering year (free PRO) | 2015-05..2016-04 | **Yes: the only real data any seat sees.** It counts as inspected from the first run (backtest contract). |
| Research corpus | 2023-01..2025-12 (BASIC on the lab) | **No.** Hidden while `research_months_ruling` is null; any use goes through Q-Y7 and the backtester. |
| Sealed holdout | 2026-01..2026-08 | **Never.** Not downloaded; lab rule 4 and `month_gate`. |
| Exposed and prospective | 2026-09 onward | **Never** on the lab. |

Markets whose month is in no split, such as the 8 members from 2016-May, are never offered to a seat.

### 4.3 The viewed-markets ledger for agents

- Every ledger row carries `actor`, and `ledger-summary` prints counts by actor, month, role and attempt. Agents still never read the ledger itself.
- Yu sets each run's sample seed, size and filters at arming. Markets are never chosen by name, by an agent or by a strategy.
- The run manifest records seed, size, filters, strategy hash, ruling id and arming channel.
- An agent run shows Yu nothing about a market. What agents themselves learn is limited to AS-7's output.
- Reconciliation with Nuance's trial ledger follows Q-N11, extended with `actor`.

### 4.4 Overfitting and multiple testing

- An agent can try many variants an hour, and some will look good by chance. So:
  - **Variants iterate on synthetic markets.** Real data is used only for armed batch runs.
  - **Every seat run is a trial**, recorded as started, failed, aborted or completed, with variant, seed, sample and code hash (Q-SN3).
  - **A fixed holdback:** a seeded 30% of the engineering year is never used while iterating, and is used once per strategy family. Even then it is not evidence: 2015-16 liquidity is not 2026 liquidity.
  - **Reports cover every market offered:** traded, passed, refused (by code), errored, or not run (by code). Never only the traded ones.
  - **A per-day run budget**, because repeated runs over overlapping samples allow differencing.

### 4.5 Labels

Every seat report carries `paper_simulation_not_execution_evidence` (paper.py:62); `agent_seat:<kind>` and either `charged_latency` or `uncharged`; the observation profile, `model_id` and cap profile; the paper-v1 assumptions (DESIGN 7.11); and the Rule-4 exclusion count (DESIGN 7.9).

### 4.6 Suite seat or `betfair/backtest`?

| Use the backtester (Nuance, `betangel_research/betfair/backtest`) when | Use a suite seat when |
|---|---|
| the question is whether a strategy has an edge | the question is how a plan executes on a ladder: resting orders, queue, cancels, green-up |
| decisions fall at fixed points over a cohort (for example T-5 min), BSP- or LTP-based, as in P0 | decisions run on a cadence through the pre-off window on PRO ticks with paper-v1 exact stepping |
| a frozen contract, an issuance ledger, research months or a registered hypothesis is needed, or a P1 (flumine) cross-check | the job is testing model plumbing (Jev, local models, Claude) on synthetic markets |

**Rule.** A seat result that looks like an edge is a reason to write a backtest contract, not evidence. S1 strategies are pure functions over `seat-obs-v1`, so they could be ported (Q-SN2).

---

## 5. Licensing and terms

### 5.1 What the terms say

| Source | What it says | Status |
|---|---|---|
| Betfair Historical Data, "Personal Use Only" | "All historical data is provided for personal, internal use only. If you'd like to use the information for commercial purposes then you'll require a commercial licence." | Quoted (site bundle, 2026-10-15). No version or date shown. |
| Same, "No onward distribution" | "The resale or distribution to, or the use of the Historical Betfair Data by, another organization or individual is strictly prohibited unless a specific agreement in writing with Betfair exists." | Quoted. It covers *use by* another organisation, not only distribution. |
| Same, IP | Betfair owns the IP "in the Historical Data and all parts and copies thereof". | Quoted |
| Same, on derivatives, processors, AI | Nothing explicit about features, statistics, trained models, cloud processors or AI. | *Inference* from absence; a support-centre search found no article. |
| General Terms 19.3 | Odds data, "both live and historical", may be used "only as strictly required for your permitted personal, non-exclusive, non-sublicensable, non-commercial purpose". Other use needs prior written consent. | Quoted (Wayback 2026-05-11, checked against a same-day copy) |
| General Terms 18.3, 12.1.4, 18.11 | Betting through the API appears permitted: 18.3 lists the API channel, and 12.1.4 exempts "bets placed via the ... API" from "robotically" placed bets. 18.11 says users of bots "do so entirely at their own risk": a risk disclaimer, not a permission. | Quoted. Relevant only to live (section 6). |
| Betfair rules naming AI agents or LLMs | None found for the Exchange. Poker rules ban AI tools for poker only. | *Inference* from absence |
| Anthropic Consumer and Commercial Terms | The user "must ensure that you have all rights, licenses, and permissions that are necessary for us to process such Inputs"; the customer "represents and warrants that it has all rights and permissions required to submit Inputs" (L.1). | Quoted |
| TypeSafe MCA §5, §4.1, §4.3, §10.3 | The customer warrants rights over the input. TypeSafe keeps a perpetual right to derive Telemetry, processed "without restriction", and may keep data in backups. | Quoted (MCA of 2026-09-23) |

### 5.2 What follows, by seat kind (*inference*)

- **S1 and S2.** The processing stays on Yu's Mac. But aggregate reports enter the authoring agent's hosted context: Anthropic's, for lab-Claude on the consumer Max login (30-day or 5-year retention, transcripts under `~/.claude/projects`). Astra is run by OpenAI, another organisation again. Rule 5 today allows agents only codes, counts, salted hashes and timings. So exposure is low, not none, and AS-7 decides what agents see.
- **S3 and S4.** Read conservatively, sending observations, even bucketed ones, to TypeSafe or Anthropic is "use ... by another organization". It needs Betfair's specific written agreement. A milder reading treats a processor acting for Yu as Yu's own use, but Betfair has not said so. Both vendors also make Yu warrant rights that the licence may not grant.
- **Until Betfair's specific written agreement for the named provider is recorded, S3 and S4 stay synthetic.** That includes lab-Claude reading real seat observations.

### 5.3 The question for Betfair (for Yu to send; lab-Claude never contacts Betfair)

> I hold a personal UK Betfair account and downloaded the free 2015-05..2016-04 horse-racing PRO Historical Data for my personal, internal use. I am writing paper-trading software for myself, on my own computer. Nothing would be published, sold or shared with other people. I would like your view, and where needed a specific written agreement, on four uses:
>
> (a) Aggregate statistics from my own simulated runs over the data (counts, fill rates, and profit and loss in coarse bands over at least 20 markets) shown to an AI coding assistant (Anthropic's Claude, hosted in the US) that helps me write the software.
>
> (b) Strategy code whose parameters were tuned on those statistics, kept in a private GitHub repository.
>
> (c) De-identified features derived from the data (price bands and time-to-off buckets, with no market ids, names or dates), sent at each simulated decision to an AI provider's API (Anthropic, or TypeSafe AI's Jev; both hosted in the US), which returns a decision for my own paper trading. The providers' terms are relevant. Anthropic's API keeps inputs for up to 30 days, and content flagged for safety for up to 2 years. TypeSafe keeps data "as long as necessary", may keep it in backups, and keeps a perpetual right to derive telemetry ("hashes, summary statistics and classifications") from inputs and use it "without restriction". Both providers require me to warrant that I have the rights to send the input.
>
> (d) Keeping derived artefacts (aggregate statistics, tuned strategy code, model weights) and using them for my own betting later.
>
> Is any of (a)-(c) "use ... by another organization" under the No onward distribution clause? If so, would Betfair give a specific written agreement, and for which named providers?

### 5.4 The OK Yu would give, per seat kind (templates, in Yu's own words)

- **S1, real data (AS-6, AS-7):** "I approve S1 agent seats placing paper orders on the 2015-05..2016-04 PRO year on the lab under proposal 001, ruling <id>, armed by me, at most <N> runs of at most <M> markets, until <date>. [AS-7 (a):] Agents see only counts and refusal codes from these runs. [Or (b):] Only lab-Claude may see seat reports with these fields: <list>, with P&L in bands of <£x>, in cells of at least 20 traded markets. Strategy code changed after a real-data run stays under ~/betangel-data and out of git."
- **S2, real data:** the S1 wording, plus "I approve installing <runtime and version> and <model and weights hash> on the lab. The model process has no network and keeps no logs outside ~/betangel-data."
- **S3, real data:** "I approve sending bucketed-v1 observations (schema sha256 <hash>), pre-off only and with no settled results, derived from the 2015-05..2016-04 PRO year, directly to api.typesafe.ai with no gateway or reseller, model <pinned id>, from the bridge on the lab, under my own TypeSafe account, for paper research only, at most $<X> a month, until <date>. Betfair's specific written agreement of <date> naming TypeSafe AI is recorded. I accept that I warrant rights over the input (MCA §5), that TypeSafe may keep it in backups and derive telemetry it can use without restriction, that data once sent cannot be recalled even if Betfair later objects, and the MCA's California law, JAMS arbitration, non-refundable prepaid credits and customer-publicity clause (§16.4)."
- **S4, real data:** the S3 wording, with "directly to api.anthropic.com under an API key on the Commercial Terms, model <pinned id>, never through Claude Code, with no Batch, Files API, MCP connector or Covered Models", Betfair's agreement naming Anthropic, and "I accept the input warranty (Commercial Terms L.1) and retention of up to 30 days, or 2 years for flagged content".

Each OK gets a ruling id. It is recorded in `session.json` and the ledger, and checked by `seat-arm`.

### 5.5 Least exposure first

Synthetic seats come first, then S1 on real data, then S2. S3 and S4 on real data come only after Betfair's specific written agreement for the named provider is recorded and the 5.4 OK is given. At every step the earlier kind must have shown the plumbing, STOP and budgets working.

---

## 6. Live, much later (direction only; adopted by no AS item)

An agent placing real bets would need all of the following, each through its own proposal under DESIGN 14:

- **The £499 live key** (D-8), after gate G1. "App Key generation is for personal betting purposes only", and read-only use of the live key is not permitted. A seat that mostly watches belongs on the delayed key or in replay. Paper never runs on live-key data (rule 9).
- **The Exchange API on Yu's own account only.** Automated betting there appears permitted (General Terms 18.3 and the API exemption in 12.1.4). 18.11 places all risk on the user. 11.2.11 prohibits "utilisation of software to gain an unfair advantage", which the Terms do not define. Under 4.5 Yu is liable for every order placed with Yu's credentials. **Never** browser automation of betfair.com. No third party (TypeSafe or any vendor) ever places bets or holds a login, app key or certificate (4.4-4.5). A vendor running bets for customers would need a Software Vendor licence, and many accounts moved in step could look like "acting in concert" (12.1.7).
- **G1 additions.** Ask Betfair whether AI-originated orders through the API on a personal account raise any issue, and whether to disclose them on the live-key application (the form needs a login and was not inspected).
- **Vendor terms re-checked** before any hosted model sits in a live loop: Anthropic's Usage Policy ("High-risk AI Recommendations", including "a personalized recommendation to buy, sell, hold, or allocate among specific investment products"; the version marked effective 2026-11-12) and TypeSafe's AUP 1.15.
- **Air side only, owned by Nuance**, in a repo never cloned on the lab. `gateway.py` stays the single choke point, with a new intent source (as P-2).
- **The typed `/dev/tty` gate and D1-D5.** A per-order retyped line does not fit an autonomous seat. A per-session arming line (as P-3) gives up the per-order human confirmation that D1-D5 rely on, so it needs its own worst-case loss analysis (caps × orders × session length).
- **Hard caps far below Betfair's limits** (transaction charges above 5,000 qualifying transactions an hour; `placeOrders` takes at most 200 instructions), starting at the live v1 defaults.
- **Kill switch and halts:** `killswitch.engage` on the Air, a heartbeat watchdog, reconcile, and a clean halt when the account is suspended or a Betfair check is pending.
- **No hosted model sees live prices** until Betfair has given its view under General Terms 19.3.
- **Evidence first:** a registered backtest on research months and a prospective record, not seat results on the engineering year.

---

## 7. Phasing

| Step | Scope | Needs | Estimate (lab work; reviews on top) |
|---|---|---|---|
| **Now, inside Phase 1b** | `actor` in `commands.jsonl`, `session.json` and notes (values `operator` and `test` only); a per-actor `customer_strategy_ref` with its own validated config (V11); a `PaperDesk` order-source type; `ledger-summary` by actor | AS-2; Nuance reviews the order-source type | about 1 day |
| **Step A: headless synthetic seat** (after MVP sign-off) | `run/seat.sock` and the guard change; the control verbs and headless runs; the lockstep scheduler; `AgentIntent` in synthetic mode; the `seat-obs-v1` builder with LTP and traded-rate trackers in checkpoints (DESIGN 6.4), and I-21; S1 in `seat-arm` with the AST allowlist and read-deny; `seat-cli` (lab-Claude's interactive use); budgets, watchdog, STOP and preemption; seat log and reports; I-20..I-24 | AS-1, AS-3, AS-5; Astra (socket, guard, control socket), Nuance (paper path, Q-SN1) | 4-6 weeks. It can split into A1 (socket, guard, headless S1, budgets, STOP) and A2 (`seat-cli`, reports). |
| **Step B: S1 on real data** | `SEAT_REAL_DATA_KINDS = {S1}`; armed batches; trial ledger and holdback; AS-7 reports | AS-6..AS-11; Nuance's AGENTS.md:9 change and a pin bump | 1-2 weeks after the rulings |
| **Step C: S2 local model** | the adapter outside this repo; runtime and weights; memory and latency measured with the engine running | AS-12 | about 1 week, plus measurement |
| **Step D: S3 and scripted S4 on synthetic** | the bridge; pinned model versions; `bucketed-v1` and its leak tests; latency measured from the lab | AS-13(a) and/or AS-14(a); TypeSafe signups open (*unknown* today) | 1-2 weeks |
| **Step E: S3 or S4 on real data** | a reviewed flag flip | Betfair's specific written agreement for the named provider; AS-13(b) or AS-14(b) | days of wiring; mostly waiting |
| **Step F: beside Yu, and advise mode** | Not lockstep: T_submit is the replay time when the reply arrives, so charged latency is wall latency × speed, and the seat never pauses Yu's clock. Yu's seek or void closes the seat's session as `voided_rewound` after STOP handling. A shared-book `PaperDesk` (each exchange takes up to half the displayed size independently, so combined fills can exceed what was there; debriefs say so). A measured two-exchange exact-mode speed. Advise mode: a distinct accept gesture (never Enter on a suggestion focused by default), the full order shown first, `suggested_by` recorded, and advised orders counted separately in the debrief and the live v1 shadow badge. A `place` body key, frame fields and a UI stop control (Astra; I-7 tests change). | AS-15 | not estimated |
| Live | — | Section 6 | not planned |

---

## 8. Decisions for Yu, and questions for Nuance and Astra

### 8.1 Decisions for Yu

**Asked now:**

| ID | Decision | Recommendation |
|---|---|---|
| **AS-1** | Accept the agent seat as a post-MVP track under this proposal. This adopts no rule text: each section 3.8 row takes effect only through the AS item named there, and section 6 is adopted by no AS item. | **Yes.** |
| **AS-2** | Build the Phase 1b seams (section 7, first row). | **Yes.** About one day added to 1b, plus Nuance's review. |
| **AS-3** | Step A: a headless seat on synthetic markets. It adopts the synthetic rule 3 row, I-8 (synthetic), the I-19 scope, the guard change and the control verbs (3.8), subject to Nuance's answer on AGENTS.md:9 (Q-SN1). Lab-Claude may then drive synthetic seats from its own shell. **It authorises no account, key, install or network egress** (see AS-12..AS-14). | **Yes, after MVP sign-off.** |
| **AS-4** | Send the section 5.3 question to Betfair Developer Support (lab-Claude drafts it; Yu sends it). | **Yes, ask; no hurry.** |
| **AS-5** | Latency accounting: lockstep with measured latency; uncharged mode labelled and excluded from results. | **Yes.** |

**At Step B (S1 on real data):**

| ID | Decision | Recommendation |
|---|---|---|
| **AS-6** | Allow `AgentIntent` paper orders on real data for S1: the real-data rows for rule 3, rules 5-6, I-8 and I-16; R-6 superseded after the MVP; Nuance's AGENTS.md:9 change; `SEAT_REAL_DATA_KINDS = {S1}`. | **Yes for S1, after Step A's evidence. Paper only**, and not a step toward live without section 6's own proposal. |
| **AS-7** | What agents may see from real-data runs. **(a)** Counts and refusal codes only; P&L goes to Yu alone. **(b)** Also P&L in coarse bands, in cells of at least 20 *traded* markets, for named agents only (for example lab-Claude), recorded as a widening of rule 5. | **(a)** until Betfair answers 5.3(a). (b) is Yu's call. |
| **AS-8** | Arming: Yu only, from the release copy at the lab's terminal, one batch per sitting (strategy-hash allowlist, at most N markets, seed and filters, budgets, expiry). It rests on conduct; the `/dev/tty` step is friction only. | **Yes.** |
| **AS-9** | Seat limits as in section 3.5. | **Yes.** |
| **AS-10** | Strategy code changed after a real-data run stays under the suite root, never in git, until Betfair answers 5.3(b) or Yu rules that it is not a derivative. | **Keep it out of git.** |
| **AS-11** | Deterministic re-runs of agent sessions on real data, headless, with AS-7 output. | **Yes, together with AS-6.** |

**Later:**

| ID | Decision | Recommendation |
|---|---|---|
| **AS-12** | S2: install llama.cpp or MLX and 2-4 GB of open weights on the lab. | **Not now.** Decide after Step B, with a measured memory plan. |
| **AS-13** | Jev. **(a)** A TypeSafe account, a key on the lab and bridge egress, for synthetic tests. **(b)** Jev on real data. | **(a) Not now.** Revisit when signups are confirmed open. If yes: Yu's own account, a spend cap, and the key in a 0600 file or Keychain item outside the repo, named by Yu. The account binds Yu to the MCA (California law, prepaid non-refundable credits). **(b)** Only with Betfair's specific written agreement naming TypeSafe AI and the 5.4 OK. |
| **AS-14** | Scripted Claude. **(a)** An Anthropic API key on the lab for the bridge, synthetic. **(b)** S4 on real data, through the API only, never Claude Code. | **(a) Not now**; only scripted runs need it. **(b)** Only with Betfair's specific written agreement naming Anthropic and the 5.4 OK. Separately, check the "help improve Claude" setting: it decides 30-day or 5-year retention for anything lab-Claude sees. |
| **AS-15** | Step F: beside Yu, and advise mode. Advise needs Yu's own ruling under R-6, because a seat-suggested order that Yu accepts is not the same as an order Yu starts (the green-up precedent starts with Yu pressing C). | **Later, after Step B.** |
| **AS-16** | Live. | **Confirm out of scope.** Agent orders never reach a live path without a new proposal under section 6. |

### 8.2 Questions for Nuance

| ID | Question |
|---|---|
| Q-SN1 | Does AGENTS.md:9 already cover strategy intents from suite seats on synthetic files, or does Step A need an amendment? Will you draft the wording for synthetic files now and for local historical files at Step B (P-1 widened, consumed only by `PaperExchange`)? |
| Q-SN2 | Should S1 strategies live in the suite or be ported into the backtester? Should `seat-obs-v1` align with the backtester's feature vocabulary? |
| Q-SN3 | May seat runs use the backtester's trial-ledger format? Add `actor` to the viewed-markets ledger format (Q-N11)? |
| Q-SN4 | U-10: an `agent_paper` intent source next to U-9's human paper source? |
| Q-SN5 | Does agent use of the engineering year affect P0 or P1, given that it already counts as inspected? Should seat runs avoid times or markets you are using? |
| Q-SN6 | Headless runs cost about 30 s of CPU per market, up to 4 h a run. Beyond the run marker, which scheduling rules do you want? |
| Q-SN7 | Should seats ever see projected SP? That would widen R-5's display-only scope (Q-N9). This draft leaves it out. |

### 8.3 Questions for Astra

| ID | Question |
|---|---|
| Q-SA1 | A seat socket with a per-run token bound to the armed kind, one connection per token, and no token on disk for real data: agreed? How should an S2 adapter or S3 bridge get a real-data token without a file? |
| Q-SA2 | Is `seat-arm`'s guard mode (one `AF_UNIX` connect path; read-deny after the strategy loads) plus the strategy AST allowlist enough, as defence in depth? |
| Q-SA3 | The bridge and S2 adapter: a separate repo? Which host allowlist, scans and run-marker checks? How should the S2 adapter's lack of egress be shown? |
| Q-SA4 | Arming rests on conduct alone (the `/dev/tty` step is easily bypassed), with the arming channel recorded: acceptable? |
| Q-SA5 | The I-21 prefix-invariance test design, and leak tests for `bucketed-v1`. |
| Q-SA6 | Is exporting place-only S1 sessions with `submit_pt = T_submit`, with engine actions replayed, enough for the parity contract? |
| Q-SA7 | The control-socket verbs `seat_arm` and `seat_stop`: shape, and the tests that change. |

---

## Appendix A. Sources (read 2026-10-15)

- **Suite and upstream (read-only):** DESIGN.md draft 0.2, sections 0-16 (`design/mvp-draft-0.2`), including the suite AGENTS.md rules (section 3.9); Phase 0a `betangel_suite/guard.py` (every connect refused at :92; `open` checked for writes only). betangel-research at 76f71dc: AGENTS.md:9; journal.py:95-97 and :210; docs/backtest-plan.md sections 3, 5, 6 and 10.
- **Betfair:** Historical Data terms (bundle https://historicdata.betfair.com/assets/en-BbBIUOj_.js); General Terms https://support.betfair.com/app/answers/detail/betfair-general-terms-and-conditions/ (403 to automated fetches; checked against https://web.archive.org/web/20260511012028/https://support.betfair.com/app/answers/detail/betfair-general-terms-and-conditions/); Application Keys https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687105/Application+Keys ; read-only live key https://support.developer.betfair.com/hc/en-us/articles/25033076334748 ; live key fee https://support.developer.betfair.com/hc/en-us/articles/115003864531 ; Software Vendor licence https://support.developer.betfair.com/hc/en-us/articles/360000391912 ; charges https://support.betfair.com/app/answers/detail/betfair-charges/
- **TypeSafe AI / Jev:** https://typesafe.ai ; https://docs.typesafe.ai/models ; https://docs.typesafe.ai/api ; https://typesafe.ai/blog/jev-1-14 ; https://typesafe.ai/blog/introducing-system-one-models-and-jev ; https://docs.typesafe.ai/model-jaggedness/jev-1.13 ; https://docs.typesafe.ai/confidence ; https://docs.typesafe.ai/sdk/python/api/retries ; https://docs.typesafe.ai/sdk/python/usage/advanced ; legal: https://typesafe.ai/legal/mca ; https://typesafe.ai/legal/privacy-policy ; https://typesafe.ai/legal/acceptable-use-policy ; https://typesafe.ai/legal/terms
- **Jev, third parties (*secondary*):** https://www.vals.ai/blogs/independent-evaluation-of-jev ; https://github.com/scienthoon/jev-ood-calibration ; https://dev.to/gde/jev-after-eight-days-of-independent-tests-level-with-mid-price-llms-behind-the-frontier-1kln ; https://flaviocopes.com/jev-api-key/ ; https://community.vercel.com/t/typesafe-ai-jev-requests-shed-with-429-and-providerattemptcount-0-per-team-throttling/49779 ; Clef: https://letsdatascience.com/news/cloudflare-releases-open-weight-clef-decision-models-c52886d6
- **Anthropic:** https://www.anthropic.com/legal/consumer-terms ; https://www.anthropic.com/legal/commercial-terms ; https://www.anthropic.com/aup ; https://code.claude.com/docs/en/data-usage ; https://privacy.claude.com/en/articles/10023548-how-long-do-you-store-my-data ; https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data ; https://platform.claude.com/docs/en/manage-claude/api-and-data-retention ; https://code.claude.com/docs/en/agent-sdk/overview ; https://code.claude.com/docs/en/cli-reference ; https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use ; latency (*secondary*): https://artificialanalysis.ai/models/claude-sonnet-5-5-low/providers ; https://artificialanalysis.ai/models/claude-4-5-haiku/providers
- **Local models and look-ahead (*secondary*):** https://github.com/ggml-org/llama.cpp/discussions/4167 ; https://omlx.ai/benchmarks ; https://unsloth.ai/docs/models/gemma-4 ; https://arxiv.org/abs/2309.17322 ; https://huggingface.co/papers/2512.23847
