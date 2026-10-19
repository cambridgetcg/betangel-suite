# Proposal 003: Agentic-first re-scope

| Status | Author | Date | Reviewers | Approver |
|---|---|---|---|---|
| Draft for review, not approved | lab-Claude | 2026-10-19 | Nuance, Astra | Yu |

**Yu's words** (2026-10-19, lab session): "No need for manual trainer". "Agents writing strategy code that then trades by itself would do". And: "more focus on how we can capture value from strategies that work on a microscale and big players wont bother". On stakes: "Well we can do £20😂 the liquidity should be able to handle it". On this draft: "Yea I do understand the drawdown. Well there may be more than 30 bets per day to be placed since there are so many matches everyday and the turnaround is fast. In-game bets are a good place to look at. confirm trainer drop and also manual live order tools. I am thinking post 2025 data would fit the best." Asked by lab-Claude, Yu chose "Horse racing in-play" and "2025 test, 2026 sealed (Recommended)"; then, on the evidence path, "Live test, no data purchase (Recommended)", which replaces the 2025 test (RS-7), and a total pilot loss limit of "£1,000".

**Yu, in chat with Nuance** (2026-10-19, as relayed by Nuance): "Personally I'd rather use the money for 實際試錯成本in betting instead of purchasing the data😂". And: "我大概預£1000 max drawdown. Lets do some research into value betting bet size control, check out rebel betting." Lab-Claude adopts Nuance's reading of these words, cited where used.

**Labels.** A bare citation means *Sourced*: W-numbers are web pages (Sources), R: is betangel-research, S: is betangel-suite, 001 and 002 are proposals. Otherwise *Measured*, *Vendor claim*, *Inference*, *Estimate* or *Unknown*. *Lab-Claude's proposal* marks a choice, not a fact.

| IDs | Glossary |
|---|---|
| BSP, CLV | Betfair Starting Price, set at the off. Closing-line value: the price taken against BSP. Calibration: price-implied against actual win rates |
| paper-v1, U-1, P0 | Upstream's conservative paper fill model; settling markets with non-runners in its P&L; the first upstream backtest contract |
| V9, U-10, D-5 | The pre-order check `validate_place` (WIN only, one winner, CLASSIC ladder); a default ladder type for old files; the DESIGN item under which Yu may change V9 |
| R-6, R-7, D-2 | Yu's Phase 0 ruling against rule-generated paper orders; Phase 0's practice cap profiles; Yu's UI choice, with a native shell before any live click |
| 001, S1-S4, AS-n, 002 | The agent-seat proposal, its seat kinds (S1: agent-written strategy code) and its questions to Yu (AS-4: a question to Betfair on licensed data); the Air viewer-files proposal |
| M-PRO, L1-L5 | The milestone where Yu watches a real race; DESIGN's later layers: native shell, delayed stream, stage-and-type live, one-click live, automation research |
| Runbook L1, C0, C1 | Upstream's layout check before a real run; the runbook's draft and frozen-contract checkouts (the lab's is C1 07aca95) |
| R10, A9, P-n, G1 | The live risk rule on the day's worst-case loss; the arming rule keeping Betfair's Heartbeat off; DESIGN §14 live proposals; checks before buying the key |

## 1. Decision

Lab-Claude proposes that the suite stop being a manual trainer. Agents write strategy code, explore it on the free data on the lab, then fit, register and freeze it. The evidence step is a pre-registered live test on the Air at small stakes (£20, Yu's figure; RS-20), judged on the bets actually matched and paused for Yu's review at £1,000 total loss (RS-16). Phase 0 stays (browser ladder, SSH viewing) to replay a strategy's orders; lab-Claude proposes it merge after the current round (RS-2). RS-1a and RS-1b list the cuts. L5 becomes the main track; proposal 002 continues unchanged.

## 2. How a micro operation captures value

**The short answer** (lab-Claude's proposal): pick niches too small to pay a firm's costs, explore on free data, test each idea live at small stakes on a low-noise price metric, and run several unrelated strategies automatically across many thin markets, so their noise partly cancels (*Inference*), under the Expert Fee line.

- **Capacity is the moat** (*Inference*). A firm's idea must pay for staff (assumed: about £100k a year per analyst-developer); a niche holding a few hundred pounds per race (assumed) cannot. One person with agents can.
- **The niche is not empty** (*Inference*). Retail bots work it too: "bots may be active in any or all Markets" (W5 cl. 18.11). So fills and speed decide who collects the pennies.

**Charges.** Basic package: 2% of net winnings per market, nothing on a losing market (W1). The Expert Fee applies only above £25k gross profit over 52 active weeks (W2). API betting is allowed (W5 cl. 12.1.4); the live key costs £499 (W3).

**What the stack cannot use today:** stakes under £1, which Betfair allows when the payout is at least £10 (W4) but the code refuses (R:paper.py:56-57; R:config.py:63); PLACE markets (family 1); and more than £50 a bet or £200 a market (R:constants.py:197-217).

**Worked example** (*Inference*, arithmetic):

- A £20 back at 5.0 that wins makes £80; commission takes £1.60, which at the fair 20% hit rate is 1.6p per £1 staked, so the gross edge must beat 1.6% there.
- At Yu's £20 stake, ten bets a day at 2% net earn about £1,460 a year and recover the key in about four months; thirty a day earn about £4,400.
- One £20 bet near 5.0 has a spread of about £40, so after 1,000 bets a genuine 2% edge can still be £1,000-2,000 down by luck. Yu's £1,000 stop is a risk stop, not a verdict on the edge.
- 2% net is a strong edge. Most ideas will show none.

**Why a price metric decides** (*Inference*, arithmetic). A £1 back at decimal odds O returns with a spread of about √(O−1). Showing a 2% profit edge at two standard errors takes about 5,000 bets at 1.5, 10,000 at 2.0 and 40,000 at 5.0: 1.4 to 11 years at 10 bets a day, whatever the stake. So profit is reported but never decides. CLV's spread per bet is a fraction of the price, so a few hundred matched bets may resolve a 2% gap. Calibration in one price band needs about 7,000 runners: the free data holds that for exploration, but live fills reach it slowly.

**Data age.** GB win-market volume has fallen every year since 2016 (W6); early-2026 pre-off volume was below 70% of 2022, on under a month of data (W7, author's measurement); a published anomaly faded from about 2018 (W8). So 2015-16 overstates today's capacity and its edges may be gone (*Inference*).

**Data** (RS-11; nothing is bought):

- **Exploration only, on the lab:** PRO 2015-16 (50 ms full ladder, in-play included) and BASIC GB/IE WIN 2023-25 (last traded price per minute, no ladder; W15), which also carries BSP and runner status (*Inference*: P0 settles at BSP on BASIC files, R:docs/backtest-plan.md:322-331).
- **Evidence:** the bets actually matched in the live test replace "a price one could take".

**Families.** Order and status are lab-Claude's proposal.

| Family | Idea, and why it may persist | Deciding metric | Fails if | Status |
|---|---|---|---|---|
| 2. Earlier price against BSP in small races | Take prices 10 to 2 minutes out that beat BSP, in low-grade races and on crowded days: per-race pre-off volume is about 40% lower on days with over 50 races than on days with 2 or fewer meetings (2022-26 data; W7) | CLV on the fills actually taken in the live test, by liquidity band, above commission's break-even | BSP is simply better, as Betfair's own study found (W10, Australia 2020-21) | Run first: explore on BASIC 2023-25 (last traded price against BSP, indicative) and PRO 2015-16; decide live |
| 5. Favourite-longshot bias, back side only | Short favourites win more often than their price says; the bias shrank on exchanges but was not zero (W14, 2006 and 2010). The lay side is blocked by the £10 liability cap | Calibration of the prices actually taken in the live test, by price band, above 2% commission plus the spread taken (PR #6 review) | The bias is gone today, or is smaller than commission and spread | Run first: explore on BASIC 2023-25 and PRO 2015-16; decide live |
| 1. PLACE priced from WIN | Derive place chances from the deeper WIN book; bet where the thin PLACE book disagrees. PLACE books carry 20-40% of WIN volume (*Vendor claim*, W9; no measurement found): the clearest niche big players won't bother with (*Inference*) | PLACE price taken against PLACE BSP, on live fills (lab-Claude's proposal) | The gap is model error: Harville, the standard place formula, is biased (*Inference*) | Needs data and a rule change: PLACE markets (Yu downloads; BASIC is free, W15), and a V9/market-type change, since V9 refuses non-WIN and multi-winner markets (R:validate.py:114-117) and live allows WIN only (R:config.py:63). Yu decides under D-5; Nuance implements upstream. The lab holds no PLACE markets at all: 0 in BASIC 2015-16, 2023, 2024 and 2025, and in PRO 2015-16 (*Measured*, Nuance's counts-01, 2026-10-19, PR #6 comment 6267797134) |
| 3. Resting orders in wide spreads | Rest small orders inside wide spreads; cancel before the off. On soccer, makers beat takers before commission; at 2% both mostly lost, except at extreme prices (W11) | Fill rate, price move after fills | Adverse selection: "losing bets are more likely to be filled" (W12) | Deferred: needs a fill model, which only PRO 2015-16 or live fills could calibrate |
| 4. Non-runner mechanics | After a withdrawal with a small reduction factor (under 2.5% in WIN, 4% in PLACE), unmatched lay offers stand (W13) | How long stale offers stand; paper fills at 500 ms | Faster bots take them. Ceiling: other runners' fair chances rise by under 2.5% relative and commission eats 1-1.6 points, so about 1% at best (*Inference*) | Watch only; U-1 gates it |
| 6. In-play, speed-free | Rest orders at prices the race may reach, such as backing at big prices for horses that may recover or laying short prices that may drift, which wait in the book and skip the delay if PASSIVE applies; or act on in-play price patterns that unfold over seconds, not milliseconds. Persists because each pays pennies per race, and the fast players chase speed (*Inference*). In-play volume has fallen faster than pre-off since 2022 (W7) | Calibration of the in-play prices actually taken in the live test, by price band and race phase, above commission and spread: BSP is set at the off, so CLV does not apply | Faster players and tracking data pick off resting orders (adverse selection, W12); or the delay applies to them | Explore on PRO 2015-16, which holds in-play; one-minute BASIC is too coarse for a race of a few minutes. PASSIVE is checked by Nuance's delayed-key definitions check on the Air (Yu, as relayed by Nuance: "2.做！"; counts only), or live |

**In-play (family 6), at Yu's request.** The fastest party wins in-play: Betfair's video runs 2-5 s behind the race (W5 cl. 20.2), some traders see the action before the TV signal (W18), and tracking data covers all RMG-owned UK courses (W17). A home bot is the slow party for anything that races the pictures (*Inference*). Some ideas are speed-free: under the PASSIVE delay model, an order that cannot match at once skips the bet delay (W16), and a race has hundreds of price moves (Yu: "the turnaround is fast"). In 2015-16 the in-play delay was 1 second and `betDelayModels` never appeared (*Measured*, RS-21), so whether today's racing uses PASSIVE is *Unknown* until Nuance's check on the Air or the live test.

## 3. The loop

1. **Write.** An agent writes a pure function (observation in, commands out; no network, files or clock) in a sandboxed process (001 §3).
2. **Explore** on the lab's free data: synthetic markets for plumbing, then PRO 2015-16 and BASIC 2023-25, with conservative fills (paper-v1: 500 ms latency, at most half of each displayed level), charged thinking time and 2% commission (R:paper.py:30-57; 001 §3.6). Exploration is never evidence (R:docs/backtest-plan.md:13, :125-142).
3. **Fit and register** on the exploration data. The fitted strategy's hash, parameters, deciding metric, pass threshold and bet count for a decision go into the tamper-evident trial ledger, and the artifact is frozen. Every start counts (R:trial_ledger.py:1-30).
4. **Live test**, the evidence step, since without bought data only a live test sees today's prices: the registered strategy, unchanged, trades on the Air at up to £20 a bet (RS-20), under the plan's rule: contract frozen, decision recorded before the event. Matched bets carry the adverse selection that historical prices hide (W12; *Inference*). A CLV decision takes a few hundred bets (§2; *Inference*); calibration takes more.
5. **Report** per run, never per market, for exploration and live tests alike: counts, refusal codes and, if RS-6 allows, the pass/fail bit. No rows, prices or per-market results reach any agent (suite rule 5; 001's covert-channel limit).

**Stop rule.** The pilot pauses for a review with Yu once the live tests have lost £1,000 in total (RS-16). The £499 key is separate.

**Against overfitting** (a placeholder for Astra's review; lab-Claude's proposal). The split is in time: the lab's data is for fitting, and only bets placed after registration are evidence. The registered artifact is never refitted once its live test starts (PR #6 review). Exploration gets a fixed budget, say 20 runs per family, with a light holdback, and reports by race code (flat, jumps, all-weather) and liquidity band, so no single season decides. Schema v1 allows no fitting (R:docs/backtest-plan.md:1384), so upstream needs schema v2 with a prospective split (RS-10). No 2026 month of historical data is downloaded (lab rule 4; R:contract.py:154-159).

**Inputs for Nuance's live draft** (RS-19, now earlier):

- The stake rule and caps (RS-20), the £1,000 stop (RS-16) and the kill switch.
- Per-session arming with a worst-case loss bound, and a dead-man watchdog. Betfair's Heartbeat stays off (A9): it would cancel Bet Angel's bets too (R:docs/betfair-order-path.md:103, :528).
- Automatic settlement: without it, R10 refused a third £2 order after two green-ups, trades hedged to equal profit (*Measured*, Nuance's probe, S:DESIGN 7.2).
- No stake above £20 per order, the ceiling Yu named (RS-20).

## 4. Where it lives

Research AGENTS.md:9 lets strategies generate simulated orders "only within betangel_research/betfair/backtest", for the offline simulator alone. Upstream has the governance (contracts, trial ledger, holdout gate) but only two fixed BSP strategies and no LIMIT fills (R:cohort.py:114, :164-166). The suite has the sandbox and exports the paper engine (S:rx.py:31-61).

A possible split (lab-Claude's proposal, for Nuance to answer; RS-5): upstream (Nuance) adds a strategy plug-in interface, LIMIT batch runs (the plan's P1), real-data runs and schema v2; the suite (lab-Claude) adds the agent harness and the replay viewer for Yu.

**Before real data.**

- **V9.** 0 of 12,208 PRO markets carry the ladder-type field, so every pre-order check fails on real data (*Measured*, Nuance, S:DESIGN 7.1). The routes are in RS-14. Families 2 and 5 read prices, not paper orders, so they need none (*Inference*).
- **Lab state.** Research PR #28 (416702f) widened the runbook's L1 check, but it reaches the lab only through a new C0, whose L1 refuses with `state_history` because lab-state holds P0's history. So any real-data run on the lab, the agents' batches included, first needs Yu's RS-13 choice (Nuance's note, 2026-10-19).

**Hard lines.**

- Lab-Claude never starts a real-data run or reads `~/betangel-data`; real runs are Nuance's or Yu's, under the run marker.
- 2026 recordings, delayed-key or live, stay on the Air and never reach the lab (lab rule 4).
- Agents see real-data results only through the report tool.
- Strategy code never runs in the engine process, which may read the data home and runs the guard in-process (Nuance's PR #2 review, round 6).
- Unattended stop and recovery, and the precedence of pending-order cancellation, get their own reviewed contract before any strategy runs on real data; the trainer's STOP design is moot under RS-1a (Astra's and Nuance's round 6 reviews).
- The pin stays at betangel-research 76f71dc until the strategy interface lands; then it moves, gated by the contract test (Nuance's PR #2 review, round 6).
- The Air loopback-service residual of the browser viewer (DESIGN 8.6, 9.4) stays open while the viewer is used: the cancelled L1 shell was its planned fix, so a reviewed deny-all content rule must replace it (Astra's PR #1 and Nuance's PR #5 reviews, round 6).

## 5. Plan and decisions

Times are lab-work *Estimates*, before review waits.

1. Merge Phase 0; write the agreed rule rows into AGENTS.md and DESIGN. About 3 days.
2. Strategy interface, sandboxed host, synthetic batch runner, per-run reports. About 2-3 weeks.
3. Explore families 2 and 5 on the free data (one snapshot per market), after RS-13; fit and register the ones exploration favours. About 1-2 weeks, plus Nuance's share (*Unknown*).
4. In parallel with steps 2-3, mostly Nuance's: the live-automation policy for Yu's written approval, a strategy order source and the safeguards (RS-19); the delayed-key plumbing check and G1's checks before buying the key (RS-18). The order source plugs in right after the harness. L4 alone was estimated at 4-8+ weeks (S:DESIGN 12).
5. The live pilot, the evidence step: each registered strategy trades at the RS-20 caps until its registered bet count or the £1,000 stop. A few hundred bets at 30 a day take about two weeks (*Inference*).

| ID | Decision | Who | Why | Lab-Claude recommends |
|---|---|---|---|---|
| RS-1a | **Confirmed by Yu, 2026-10-19** ("confirm trainer drop"). Cancel the manual trainer: 1a's UI; 1b's operator paths (OperatorClick, practice stop, exploration mode, R-7's learning target, Yu's practice races); all of 1c; the L1 native shell, with D-2's native-shell clause. Defer M-PRO's "Yu watches a real race" and L2. Keep 1a's data layer and 1b's paper core headless only if batch runs live in the suite | Yu | Yu: "No need for manual trainer" | Yes |
| RS-1b | **Confirmed by Yu, 2026-10-19** ("and also manual live order tools"). Cancel L3 (stage-and-type live) and L4 (one-click live) | Yu | These are manual live tools, not training, so Yu's words do not settle them | Done |
| RS-2 | Lab-Claude proposes Phase 0 merge after the current round, residuals as documented | Nuance and Astra accept; Yu for AGENTS.md changes | Its guard (no network, fixed write roots), pin, `rx.py` allowlist, launcher, run marker, hygiene scanner, synthetic generator and release copies serve the agent loop | Yes |
| RS-3 | Supersede R-6; amend suite rule 3 for strategy orders consumed only by PaperExchange | Yu; Nuance and Astra review | R-6 and rule 3 ("no rule-generated orders"; every real-data paper order is a click) forbid the loop | Yes, synthetic first; real data once RS-5 is settled |
| RS-4 | Absorb 001's S1 path, its hygiene rules and AS-6..AS-11; "after MVP sign-off" becomes "after Phase 0 merges"; defer S2-S4 and advise mode | Yu | S1 is the closest existing design | Yes |
| RS-5 | Where batch runs live, and who runs real batches (§4). The alternative to §4's split, batch runs in the suite (001 Steps A-B), needs Nuance's AGENTS.md:9 wording | Nuance proposes; Yu approves | Research AGENTS.md:9 confines strategy order intents to `betfair/backtest` | Question for Nuance |
| RS-6 | What agents see from real data: (a) one pass/fail bit per pre-registered family test, an aggregate over thousands of markets; or (b) counts and codes only, until Betfair answers the AS-4 question. Either way, reports per run, never per market | Yu; Betfair for any agreement | The licence is for Yu's personal, internal use; use by another organisation needs Betfair's written agreement (001 §5.1), and hosted models on real data need one naming the provider. One bit over thousands of markets reveals no row, price or market (*Inference*); per-market reports could leak through a covert channel (001) | Lab-Claude's lean: (a). The AS-4 question is not sent yet: lab-Claude drafts it when Yu asks (Yu's AS-4 answer, 2026-10-17) |
| RS-7 | Evidence gate: the free data on the lab (PRO 2015-16, BASIC 2023-25) is for engineering and exploration only; the evidence is the pre-registered live test at stakes up to £20, judged on the bets actually matched; no 2026 month of historical data is downloaded | Yu chose "Live test, no data purchase (Recommended)" (2026-10-19), which replaces the 2025 test and keeps "2026 sealed"; Astra reviews | The plan and 001 say 2015-16 is not evidence (R:docs/backtest-plan.md:13, :140; 001). Free data shows no price one could take today. Paper trading on live-key data is not allowed, and the free delayed key is 1-180 s late, conflated and 3 levels deep, so it checks plumbing only (W3; S:DESIGN 2.3, 12; R:constants.py:164-167) | Yes |
| RS-8 | Deciding metrics, read on the live test's matched bets: CLV for family 2; calibration of the prices actually taken, above commission and spread, for families 5 and 6. Profit is reported, never decides. The bet count for a decision is registered first: a few hundred for CLV (§2; *Inference*) | Yu; Astra reviews | A 2% profit edge needs 5,000-40,000 bets (§2). Nuance's reading: "CLV (or calibration) on the fills actually taken" | Yes |
| RS-9 | Splits and budget: the lab's data for fitting, with a light holdback; evidence only from live bets placed after registration; reports by race code and liquidity band; 20 exploration runs per family | Astra reviews; Yu | Seasons differ: March-April holds Cheltenham and Aintree, and January-February is all-weather and jumps | Placeholder for Astra |
| RS-10 | Schema v2 with a prospective split: fitted on the lab's data, registered and frozen, then judged only on live bets placed after registration | Nuance (upstream); Astra reviews | Schema v1's registered hypothesis allows no fitting (R:docs/backtest-plan.md:1384) | Yes (Nuance's reading); the design is Nuance's |
| RS-11 | **Closed by Yu, 2026-10-19** ("Live test, no data purchase (Recommended)"). No ADVANCED or PRO purchase. Exploration uses what the lab holds: PRO 2015-16 and BASIC GB/IE WIN 2023-25 (GB 10,357 and IE 2,981 WIN markets in 2025; Nuance's counts-01, 2026-10-19, PR #6 comment 6267797134). Never any 2026 month | Yu | Yu, as relayed by Nuance: "Personally I'd rather use the money for 實際試錯成本in betting instead of purchasing the data😂". Live fills replace a price one could take | Done |
| RS-12 | Family 1: PLACE markets in recent data, and a V9/market-type change. First, a count of PLACE markets in the lab's year (counts only) | Yu under D-5; Nuance implements and counts | V9 and the live rules refuse PLACE (R:validate.py:114-117; R:config.py:63) | Counted: 0 PLACE markets on the lab (Nuance's counts-01, 2026-10-19, PR #6 comment 6267797134). Family 1 needs PLACE downloads; decide after families 2 and 5 report |
| RS-13 | Lab state for any new real-data run: a new state root, or a reviewed state-gate change | Yu; Nuance | A new C0's L1 refuses with `state_history` (§4). The widened L1 "lands" when the lab's research checkout is at a C0 that includes 416702f, and no suite command runs between that L1 and 5a (Nuance's PR #1 review, round 6, F4) | Ask Nuance for options first |
| RS-14 | Before V9 on real data: U-10, a labelled run without V9, or Yu's D-5 ruling. Then U-1, or the indicative figure, for P&L | Nuance; Yu for D-5 | 0 of 12,208 markets carry the ladder field. Markets with any non-runner are 49.5% of the year (review judges' count, S:DESIGN 2.4), and paper-v1 leaves them out of P&L (R:paper.py:52-53), which biases exploration's P&L but not the price metrics (*Inference*) | Nuance's call on the route |
| RS-15 | A review gate for agent-written code before live; the live code hash equals the pre-registered hash | Yu decides; Astra reviews | A strategy that trades by itself must be the one that was tested | Yes |
| RS-16 | **Set by Yu, 2026-10-19** ("£1,000"). Pilot loss limit: £1,000 in total across the live tests; reaching it pauses them for a review with Yu. The £499 key is separate. Set before buying the key (G1) | Yu | At £20 stakes luck alone can swing £1,000-2,000 over 1,000 bets (§2). Yu, as relayed by Nuance: "我大概預£1000 max drawdown." | Done |
| RS-17 | Bot bets and Yu's own bets on one account | Yu; Nuance | Yu said "bet angel never used" (2026-10-15), but any manual bets share commission netting, caps and the Expert Fee test | The bot stays out of markets Yu trades, or attribution rules |
| RS-18 | Delayed-key plumbing check; G1 checks before buying the key (ask Betfair support; the loss limit is RS-16) | Yu; Nuance | The live test is the evidence step, so its path must be ready when exploration ends. The delayed key cannot reproduce pre-off fills | Earlier: right after the harness, in parallel with exploration (Nuance's reading) |
| RS-19 | Upstream live-automation policy, plus a strategy order source, a long-lived session and §3's safeguards (S:DESIGN P-2..P-5, P-11) | Yu approves in writing (R:docs/betfair-order-path.md:630). Lab-Claude's proposal: Nuance drafts and Astra reviews, as for L4 (S:DESIGN 12) | Research AGENTS.md:10 allows only orders "the operator types at a terminal"; the gateway refuses `source="api"` live (R:gateway.py:863) | Earlier: right after the harness, in parallel with exploration (Nuance's reading). Yu still approves the policy in writing |
| RS-20 | Live pilot stake rule and caps, in Nuance's config on the Air. £20 per order stays the ceiling Yu named. The stake rule under it, and the caps, follow Nuance's research on value-betting stake control, including RebelBetting. Lab-Claude's draft until then: £20 worst-case loss per order, £40 per market, £150 across markets, £200 daily loss; order-rate caps unchanged (200 orders a day). All within the hard ceilings (£50, £100, £200, £500, £200; R:constants.py:197-217), so a setting change, not code | Nuance researches and proposes; Yu approves ("we can do £20"); Nuance sets the config when the pilot starts | Yu, as relayed by Nuance: "Lets do some research into value betting bet size control, check out rebel betting." A £20 back carries £20 of liability, above today's £10 per-order cap, so the caps must rise together. Liquidity near the off can take £20 in most GB WIN markets; thin niches may part-fill (*Inference*). Yu expects more than 30 bets a day; at 50 £20 bets a day an ordinary day swings about ±£280, so a £100 daily limit would stop many normal days. Above £200 needs a code change (*Inference*) | Open until Nuance's staking research; nothing changes before the pilot |
| RS-21 | Counts from the lab's 2015-16 PRO files: in-play `betDelay` values and `betDelayModels` for GB/IE WIN markets (counts only) | Nuance | Family 6 depends on how long the delay is and whether resting orders skip it | Done: 1 s in-play in all 11,812 in-play markets, 0 before the off; `betDelayModels` in none of the 437,228 definitions (Nuance's counts-01, 2026-10-19, PR #6 comment 6267797134). PASSIVE today: Nuance's delayed-key definitions check on the Air (Yu, as relayed by Nuance: "2.做！"; counts only), or live |

## Sources

Public pages read 2026-10-19; Betfair help pages through the dated Wayback copies shown. DD = https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/

- W1. Betfair Charges, §4, §7 and §9 (Wayback 2025-07-17): https://web.archive.org/web/20250717193515/https://support.betfair.com/app/answers/detail/betfair-charges/
- W2. Expert Fee FAQs (Wayback 2026-01-11): https://web.archive.org/web/20260111205811/https://support.betfair.com/app/answers/detail/expert-fee-faqs
- W3. Application Keys (updated 2026-05-07): DD/2687105
- W4. Additional Information (updated 2026-09-04): DD/2686993; placeOrders (updated 2026-07-31): DD/2687496
- W5. Betfair General Terms and Conditions, cl. 12.1.4, 18.11 and 20.2 (Wayback 2026-05-11): https://web.archive.org/web/2026/https://support.betfair.com/app/answers/detail/betfair-general-terms-and-conditions/
- W6. Racing Post, 2024-12-18: https://www.racingpost.com/news/britain/betfair-exchange-to-introduce-new-commission-system-for-2025-as-premium-charge-is-dropped-a7wbg0v4GCAJ/
- W7. M. Berk, 2026-01-24 (UK WIN, March 2022 to January 2026): https://algorithmicsportsbetting.substack.com/p/two-markets-one-race-degeneracy-and
- W8. M. Berk, 2026-02-22: https://algorithmicsportsbetting.substack.com/p/should-you-really-bet-against-sonic
- W9. Vendor blogs on PLACE volume (2026): https://botblog.co.uk/betfair-place-market-trading/ ; https://racingplacebetting.com/betfair-exchange-place-markets/
- W10. Betfair Automation Hub (Australian thoroughbreds, 2020-21): https://betfair-datascientists.github.io/tutorials/analysingAndPredictingBSP/ ; https://betfair-datascientists.github.io/tutorials/analysingAndPredictingMarketMovements/
- W11. K. Whelan, MPRA 126351 (version 2026-01-26): https://mpra.ub.uni-muenchen.de/126351/
- W12. Betfair Automation Hub, Golden Rules of Automation: https://betfair-datascientists.github.io/tutorials/goldenRulesOfAutomation/
- W13. Exchange Horse Racing Rules (Wayback 2025-09-26): https://web.archive.org/web/2025/https://support.betfair.com/app/answers/detail/exchange-horse-racing-rules/
- W14. Smith, Paton and Vaughan Williams, Economica 73 (2006): https://ideas.repec.org/a/bla/econom/v73y2006i292p673-689.html ; Smith and Vaughan Williams, IJF 26(3) (2010): https://ideas.repec.org/a/eee/intfor/v26yi3p543-550.html
- W15. Historic data tiers (both undated; neither gives ADVANCED or PRO prices): Betfair Hub, "Historical data sources": https://www.betfair.com.au/hub/education/how-to-model/historical-data-sources/ ; Betfair Automation Hub, "Historic Data Site": https://betfair-datascientists.github.io/data/usingHistoricDataSite/
- W16. Betting Enums, `betDelayModels` (updated 2026-07-17): DD/2687455
- W17. M. Berk, 2026-03-31 (TPD tracking at RMG-owned UK courses): https://algorithmicsportsbetting.substack.com/p/crises-create-opportunities
- W18. Brown, *Applied Economics* 44(9), 2012 (in-play traders ahead of the TV signal): https://ueaeprints.uea.ac.uk/id/eprint/45783/

Repository sources, read-only on 2026-10-19: betangel-research main 0d32421 (R:; bare `.py` names are in `betangel_research/betfair/`, or its `backtest/` for cohort, contract and trial_ledger), and commit 416702f (research PR #28) for the runbook L1 change; betangel-suite r4-viewing 52a9edc (S:; `rx.py` is in `betangel_suite/`); proposal 001 (`docs/proposals/001-agent-seat.md`, branch proposal-001). Nuance's note of 2026-10-19 is lab inbox `20261019T102907Z-air.md`, and Nuance's relays of Yu's chat words that day are `20261019T132343Z-air.md` and `20261019T132613Z-air.md`; Yu's 2026-10-15 words are recorded in lab outbox `20261015T135837Z-lab-suite-rulings.md`. Working notes: `round6/rescope/market-facts.md` and `round6/rescope/code-inventory.md` in lab-Claude's session scratchpad.
