# Proposal 003: Agentic-first re-scope

| Status | Author | Date | Reviewers | Approver |
|---|---|---|---|---|
| Draft for review, not approved | lab-Claude | 2026-10-19 | Nuance, Astra | Yu |

**Yu's words** (2026-10-19, lab session): "No need for manual trainer". "Agents writing strategy code that then trades by itself would do". And: "more focus on how we can capture value from strategies that work on a microscale and big players wont bother". On stakes, after lab-Claude explained the live caps: "Well we can do £20😂 the liquidity should be able to handle it". On this draft: "Yea I do understand the drawdown. Well there may be more than 30 bets per day to be placed since there are so many matches everyday and the turnaround is fast. In-game bets are a good place to look at. confirm trainer drop and also manual live order tools. I am thinking post 2025 data would fit the best." Asked by lab-Claude to pin two points down, Yu chose "Horse racing in-play" and "2025 test, 2026 sealed (Recommended)".

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

Lab-Claude proposes that the suite stop being a manual trainer. Agents write strategy code, it is explored in batch on historical replay, and a strategy that passes a pre-registered test on recent data trades by itself, at small stakes (£20, Yu's figure; RS-20), on the Air. Phase 0 stays, with the browser ladder and SSH viewing to replay a strategy's orders, and lab-Claude proposes Phase 0 merge after the current round (RS-2). RS-1a and RS-1b list the cuts. L5 becomes the main track, and proposal 002 continues unchanged.

## 2. How a micro operation captures value

**The short answer** (lab-Claude's proposal): pick niches too small to pay a firm's costs, prove each idea on a low-noise price metric before staking, then run several unrelated small strategies automatically across many thin markets at small stakes, under the Expert Fee line.

- **Capacity is the moat** (*Inference*). A firm's idea must pay for staff (assumed: about £100k a year per analyst-developer); a niche holding a few hundred pounds per race (assumed) cannot. One person with agents can live inside it.
- **The niche is not empty** (*Inference*). Retail bots, Bet Angel and Gruss users among them, work the same markets: "bots may be active in any or all Markets" (W5 cl. 18.11). Capacity keeps firms out, not hobbyists, so fills and speed decide who collects the pennies.
- **Stack many small edges** (lab-Claude's proposal). Several uncorrelated families run automatically across many thin markets, each under the radar; their returns add while their noise partly cancels (*Inference*). The Expert Fee is nil below £25k gross profit a year (W2).

**Charges.** Basic package: 2% of net winnings per market, nothing on a losing market (W1). Expert Fee: only above £25k gross profit over 52 active weeks; weekly, (gross P&L − Buffer) × 20% (40% above £100k), minus commission generated, which is (commission paid + 2.5% of market losses) ÷ 2 (W2). Under 0.5% of customers pay it (W1 §9.2). API betting is allowed (W5 cl. 12.1.4); the live key costs £499 (W3).

**What the stack cannot use today:** stakes under £1, which Betfair allows when the payout is at least £10 (W4) but paper-v1 and the live gateway refuse (R:paper.py:56-57; R:config.py:63); lays above 11.0 at minimum stake, which break the £10 liability cap; PLACE markets (family 1); and more than £50 a bet or £200 a market, the code's hard ceilings (R:constants.py:197-217).

**Worked example** (*Inference*, arithmetic):

- A £2 back at 5.0 that wins makes £8; commission takes 16p, which at the fair 20% hit rate is 1.6p per £1 staked, so the gross edge must beat 1.6% there.
- Live defaults are £2 stake, £10 liability, £20 per market, £50 total, £20 daily loss and 6 orders a minute (R:config.py:58-62). Ten bets a day at 2% net earn about £146 a year, so the £499 key would take about 3.4 years to recover.
- At Yu's £20 stake (RS-20), ten bets a day at 2% net earn about £4 a day, about £1,460 a year, and the key is recovered in about four months; thirty bets a day earn about £4,400 a year. Swings are large: at prices near 5.0 one £20 bet has a spread of about £40, so after 1,000 bets a genuine 2% edge can still be £1,000-2,000 down by luck alone (*Inference*). Hence a total pilot loss limit (RS-16).
- At an assumed £300 matched per market (a constants change: Nuance's code, Yu's approval), 10 markets a day at 2% net make about £22k a year. At prices near 5.0, commission is about £18k, so gross profit nears £40k and the Expert Fee test applies; its commission credit likely cancels the fee (W2's formula).
- 2% net is a strong edge. Most ideas will show none.

**Why a price metric decides** (*Inference*, arithmetic). A £1 back at decimal odds O returns with a spread of about √(O−1). Showing a 2% profit edge at two standard errors takes about 5,000 bets at 1.5, 10,000 at 2.0 and 40,000 at 5.0: 1.4 to 11 years at about 10 bets a day. A larger stake does not shorten this: the count of bets is what matters. So profit is reported but never decides. CLV's spread per bet is a fraction of the price, so hundreds of bets may resolve a 2% gap. Calibration in one price band needs about 7,000 runners, which three recent years should hold. Exploration measures both.

**Data age.** GB win-market volume has fallen every year since 2016 (W6). Early-2026 pre-off volume was below 70% of 2022, on under a month of data (W7, author's measurement). A published anomaly faded from about 2018 (W8). So 2015-16 overstates today's capacity and its edges may be gone (*Inference*).

**Families.** Order and status are lab-Claude's proposal.

| Family | Idea, and why it may persist | Deciding metric | Fails if | Status |
|---|---|---|---|---|
| 2. Earlier price against BSP in small races | Take prices 10 to 2 minutes out that beat BSP, in low-grade races and on crowded days: per-race pre-off volume is about 40% lower on days with over 50 races than on days with 2 or fewer meetings (2022-26 data; W7) | CLV by liquidity band, above commission's break-even, on all markets | BSP is simply better, as Betfair's own study found (W10, Australia 2020-21) | Run first |
| 5. Favourite-longshot bias, back side only | Short favourites win more often than their price says; the bias shrank on exchanges but was not zero (W14, 2006 and 2010). The lay side is blocked by the £10 liability cap | Calibration of the best back price on offer at decision time, by price band over all runners in all markets, then by liquidity band and month. It passes only if the calibrated advantage exceeds 2% commission plus the spread taken (PR #6 review). BASIC's last traded price can explore the bias but cannot gate it, because nobody could take it | The bias is gone in 2025, or is smaller than commission and spread | Run first: explore on BASIC; the gate needs ADVANCED or PRO |
| 1. PLACE priced from WIN | Derive place chances from the deeper WIN book; bet where the thin PLACE book disagrees. PLACE books carry 20-40% of WIN volume (*Vendor claim*, W9; no measurement found): the clearest niche big players won't bother with (*Inference*) | PLACE price taken against PLACE BSP (lab-Claude's proposal) | The gap is model error: Harville, the standard place formula, is biased (*Inference*) | Needs data and a rule change: PLACE markets in recent data (Yu downloads), and a V9/market-type change, since V9 refuses non-WIN and multi-winner markets (R:validate.py:114-117) and live allows WIN only (R:config.py:63). Yu decides under D-5; Nuance implements upstream. The lab's year likely holds few PLACE markets (12,200 of 12,208 are GB/IE WIN; S:DESIGN 2.4, 7.1; *Inference*), so lab-Claude asks Nuance for a count (counts only) |
| 3. Resting orders in wide spreads | Rest small orders inside wide spreads; cancel before the off. On soccer, makers beat takers before commission; at 2% both mostly lost, except at extreme prices (W11) | Fill rate, price move after fills | Adverse selection: "losing bets are more likely to be filled" (W12) | Deferred: needs a fill model calibrated on PRO data |
| 4. Non-runner mechanics | After a withdrawal with a small reduction factor (under 2.5% in WIN, 4% in PLACE), unmatched lay offers stand (W13) | How long stale offers stand; paper fills at 500 ms | Faster bots take them. Ceiling: other runners' fair chances rise by under 2.5% relative and commission eats 1-1.6 points, so about 1% at best (*Inference*) | Watch only; U-1 gates it |
| 6. In-play, speed-free | Rest orders at prices the race may reach, such as backing at big prices for horses that may recover or laying short prices that may drift, which wait in the book and skip the delay if PASSIVE applies; or act on in-play price patterns that unfold over seconds, not milliseconds. Persists because each pays pennies per race, and the fast players chase speed (*Inference*) | Calibration of in-play prices against outcomes, by price band and race phase, over all runners: BSP is set at the off, so CLV does not apply | Faster players and tracking data pick off resting orders (adverse selection, W12); or the delay applies to them | Explore on 2015-16 PRO, which holds in-play; needs RS-21's counts first. Recent tests need ADVANCED or PRO data: one-minute BASIC is too coarse for a race of a few minutes |

**Non-runners shrink every family's P&L sample.** Markets with any non-runner (review judges' count, S:DESIGN 2.4) are 49.5% of the year, and paper-v1 leaves them out of P&L (R:paper.py:52-53), so what remains is smaller and biased (*Inference*). Families 2 and 5 measure their price metrics on all markets, which needs no settlement.

**In-play (family 6), at Yu's request.** Lab-Claude's first draft left in-play out, because the fastest party wins there: Betfair's video runs 2-5 s behind the race (W5 cl. 20.2), some traders see the action before the TV signal (W18), and low-latency tracking data now covers all RMG-owned UK courses (W17). A home bot is the slow party for anything that races the pictures (*Inference*). Two things make some in-play ideas speed-free. Each market's bet delay holds an order that could match at once, but under the PASSIVE delay model an order that cannot match at once skips the delay (W16); and a race has hundreds of price moves in a few minutes, so there are many bets a day (Yu: "the turnaround is fast"). Whether GB/IE racing uses PASSIVE, and how long its delay is, are *Unknown*; the lab's 2015-16 PRO files carry `betDelay` and `betDelayModels`, so Nuance can count them (RS-21). In-play volume has fallen faster than pre-off since 2022 (W7).

**Recent data by tier** (W15, read 2026-10-19; family columns are *Inference*):

| Tier | Contents | Price | Family 2 | Family 5 | Family 1 |
|---|---|---|---|---|---|
| BASIC | Last traded price per minute; no ladder, no volume | Free | Indicative only: a last traded price is not a price one could take | Explore only: the gate needs a price one could take | Indicative gap only |
| ADVANCED | 1-second ladder, top 3 levels; volume | *Unknown* ("cost associated") | Needed: best back price at decision time, and volume for liquidity bands | Needed for the gate: best back price, and liquidity bands | Needed for both books |
| PRO | 50 ms full ladder; volume | *Unknown* | Not needed | Not needed | Not needed (families 3 and 4 would need it) |

The public pages list BSP without naming a tier (W15). The upstream P0 contract settles at BSP on BASIC files (R:docs/backtest-plan.md:322-331, :1222), and the review judges counted non-runners on BASIC's index, so BASIC carries BSP and runner status (*Inference*).

## 3. The loop

1. **Write.** An agent writes a pure function (observation in, commands out; no network, files or clock) in a sandboxed process (001 §3).
2. **Explore.** Synthetic markets for plumbing, then 2015-16 with conservative fills (paper-v1: 500 ms latency, at most half of each displayed level), charged thinking time and 2% commission (R:paper.py:30-57; 001 §3.6). Exploration only picks ideas to register; it is never evidence (R:docs/backtest-plan.md:13, :125-142).
3. **Fit, then register.** The recent data is split first: fitting months and held-back months (below). A family's few parameters are fitted on the fitting months only. Then the fitted strategy's hash, its parameters, one deciding metric and its pass threshold go into the tamper-evident trial ledger, before the held-back months are opened. Every start counts (R:trial_ledger.py:1-30).
4. **Test** the registered strategy, unchanged, on the held-back months of 2025, Yu's choice, adding 2023-24 only if 2025 holds too few races; the upstream plan's research corpus is 2023-01..2025-12 (R:docs/backtest-plan.md:140). Never any 2026 month: January to August 2026 stays sealed, the plan's one-time final check.
5. **Report** per run, never per market: counts, refusal codes and, if RS-6 allows, the pass/fail bit. No rows, prices or per-market results reach any agent (suite rule 5; 001's covert-channel limit).
6. **Prospective test:** live at small stakes (RS-20), under the plan's rule: contract frozen, decision recorded before the event.

**Against overfitting** (a placeholder for Astra's review; lab-Claude's proposal). Exploration on 2015-16 needs only a light holdback. On recent data the split comes first: interleaved whole months, one per quarter, are held back and used once per family; the other months are for fitting. Fitting happens only on those, before registration; the registered artifact is never refitted after the held-back months open (PR #6 review). Whole months, because a day's races share conditions (*Inference*). Results are reported by race code (flat, jumps, all-weather) and liquidity band, so no single season decides. Schema v1 allows no fitting (R:docs/backtest-plan.md:1384), so this needs schema v2 or a labelled exploration ledger (RS-10). Exploration gets a fixed budget, say 20 runs per family. The 2026 holdout stays sealed and undownloaded (lab rule 4; R:contract.py:154-159).

**Compute.** Stepping every market of the year costs about 100 CPU hours (*Estimate*, 001 §3.6), so 20 runs for three families would take about 4,000 (*Inference*). Families 2 and 5 instead read one snapshot per market at a fixed time, which is far cheaper (*Inference*).

**Forward test.** Paper trading on live-key data is not allowed (W3; S:DESIGN 2.3). The free delayed key is 1-180 s late, conflated, 3 levels deep and lacks per-runner volume (W3; R:constants.py:164-167), so a delayed-key shadow is a plumbing check, not evidence (S:DESIGN 12, L2 row). Live at small stakes is the only forward test. It is too slow to prove a profit edge (§2), so it checks the registered price metric.

**Live at micro stakes: inputs for Nuance's draft.**

- The pilot caps (RS-20) and the kill switch.
- Per-session arming with a worst-case loss bound, and a dead-man watchdog. Betfair's Heartbeat stays off (A9) because it would cancel Bet Angel's bets too (R:docs/betfair-order-path.md:103, :528).
- Automatic settlement: without it, R10 refused a third £2 order after two green-ups, trades hedged to equal profit (*Measured*, Nuance's probe, S:DESIGN 7.2).
- No stake rise until the live count computed from §2's arithmetic is reached and the metric still passes; Yu approves each step (lab-Claude's proposal).

## 4. Where it lives

Research AGENTS.md:9 lets strategies generate simulated orders "only within betangel_research/betfair/backtest", for the offline simulator alone. A real backtest ran there on 2026-10-17 (operator not named; R:docs/backtest-plan.md:1222). Upstream has the governance (contracts, trial ledger, holdout gate) but only two fixed BSP strategies and no LIMIT fills (R:cohort.py:114, :164-166). The suite has the sandbox and exports the paper engine (S:rx.py:31-61).

A possible split (lab-Claude's proposal, for Nuance to answer): upstream (Nuance) adds a strategy plug-in interface, LIMIT batch runs (the plan's P1) and real-data runs; the suite (lab-Claude) adds the agent harness (sandboxed host, synthetic iteration, per-run reports) and the replay viewer for Yu. The alternative, batch runs in the suite (001 Steps A-B), needs Nuance's AGENTS.md:9 wording.

**Before real data.**

- **V9.** 0 of 12,208 PRO markets carry the ladder-type field, so every pre-order check fails on real data (*Measured*, Nuance, S:DESIGN 7.1). The routes are U-10, a labelled run without V9 (as `run_paper_replay` does), or Yu's D-5 ruling. Families 2 and 5 read prices, not paper orders, so they need none (*Inference*).
- **Lab state.** Research PR #28 (main 416702f, 2026-10-19) widened the runbook's L1 check to accept `suite.noindex/` and `historic-pro/`. It reaches the lab only through a new C0, whose L1 refuses with `state_history` because lab-state holds P0's history. So any real-data run on the lab, the agents' batches included, first needs Yu's choice between a new state root and a reviewed state-gate change (Nuance's note, 2026-10-19; RS-13).

**Hard lines.**

- Lab-Claude never starts a real-data run or reads `~/betangel-data`; real runs are Nuance's or Yu's, under the run marker.
- 2026 recordings, delayed-key or live, stay on the Air and never reach the lab (lab rule 4).
- Agents see real-data results only through the report tool.

## 5. Plan and decisions

Times are lab-work *Estimates*, before review waits.

1. Merge Phase 0; write the agreed rule rows into AGENTS.md and DESIGN. About 3 days.
2. Strategy interface, sandboxed host, synthetic batch runner, per-run reports. About 2-3 weeks.
3. Explore families 2 and 5 on 2015-16 (snapshot reads), after RS-13. About 1-2 weeks, plus Nuance's share (*Unknown*).
4. Registered tests on 2025 for the families exploration favours, after Yu's download and Nuance's ingest (waits *Unknown*).
5. Only after a pass on recent data: the delayed-key plumbing check, then a live pilot at the RS-20 caps. Mostly Nuance's; L4 alone was estimated at 4-8+ weeks (S:DESIGN 12).

| ID | Decision | Who | Why | Lab-Claude recommends |
|---|---|---|---|---|
| RS-1a | **Confirmed by Yu, 2026-10-19** ("confirm trainer drop"). Cancel the manual trainer: 1a's UI; 1b's operator paths (OperatorClick, practice stop, exploration mode, R-7's learning target, Yu's practice races); all of 1c; the L1 native shell, with D-2's native-shell clause. Defer M-PRO's "Yu watches a real race" and L2. Keep 1a's data layer and 1b's paper core headless only if batch runs live in the suite | Yu | Yu: "No need for manual trainer" | Yes |
| RS-1b | **Confirmed by Yu, 2026-10-19** ("and also manual live order tools"). Cancel L3 (stage-and-type live) and L4 (one-click live) | Yu | These are manual live tools, not training, so Yu's words do not settle them | Done |
| RS-2 | Lab-Claude proposes Phase 0 merge after the current round, residuals as documented | Nuance and Astra accept; Yu for AGENTS.md changes | Its guard (no network, fixed write roots), pin, `rx.py` allowlist, launcher, run marker, hygiene scanner, synthetic generator and release copies serve the agent loop | Yes |
| RS-3 | Supersede R-6; amend suite rule 3 for strategy orders consumed only by PaperExchange | Yu; Nuance and Astra review | R-6 and rule 3 ("no rule-generated orders"; every real-data paper order is a click) forbid the loop | Yes, synthetic first; real data once RS-5 is settled |
| RS-4 | Absorb 001's S1 path, its hygiene rules and AS-6..AS-11; "after MVP sign-off" becomes "after Phase 0 merges"; defer S2-S4 and advise mode | Yu | S1 is the closest existing design | Yes |
| RS-5 | Where batch runs live, and who runs real batches (§4) | Nuance proposes; Yu approves | Research AGENTS.md:9 confines strategy order intents to `betfair/backtest` | Question for Nuance |
| RS-6 | What agents see from real data: (a) one pass/fail bit per pre-registered family test, an aggregate over thousands of markets; or (b) counts and codes only, until Betfair answers the AS-4 question. Either way, reports per run, never per market | Yu; Betfair for any agreement | The licence is for Yu's personal, internal use; use by another organisation needs Betfair's written agreement (001 §5.1), and hosted models on real data need one naming the provider. One bit over thousands of markets reveals no row, price or market (*Inference*); per-market reports could leak through a covert channel (001) | Lab-Claude's lean: (a). The AS-4 question is not sent yet: lab-Claude drafts it when Yu asks (Yu's AS-4 answer, 2026-10-17) |
| RS-7 | Evidence gate: 2015-16 for engineering and exploration only; evidence is a pre-registered test on 2025 (2023-24 only if needed); live at small stakes is the prospective test; 2026 stays sealed | Yu chose "2025 test, 2026 sealed" (2026-10-19); Astra reviews | The plan and 001 say 2015-16 is not evidence (R:docs/backtest-plan.md:13, :140; 001) | Yes |
| RS-8 | Deciding metrics: CLV for family 2, calibration over all runners for family 5. Profit is reported, never decides. No stake rise before the computed count; each step is Yu's | Yu; Astra reviews | A 2% profit edge needs 5,000-40,000 bets (§2) | Yes |
| RS-9 | Splits and budget: a light holdback on 2015-16; interleaved whole months (one per quarter) on recent data; reports by race code and liquidity band; 20 exploration runs per family | Astra reviews; Yu | Seasons differ: March-April holds Cheltenham and Aintree, and January-February is all-weather and jumps | Placeholder for Astra |
| RS-10 | Schema v2 or a labelled exploration ledger, for splits | Nuance; Astra reviews | Schema v1's registered hypothesis allows no fitting (R:docs/backtest-plan.md:1384) | Nuance's choice |
| RS-11 | Recent data to download: GB/IE WIN for 2025 (2023-24 only if needed); never any 2026 month. Which tier | Yu downloads; Nuance ingests | Evidence needs recent data. BASIC is free; ADVANCED and PRO prices are *Unknown* (W15). Families 2 and 6 need ADVANCED or PRO | BASIC 2025 now, to explore family 5; ADVANCED or PRO 2025 for any gate, since the gates use prices one could take (families 2, 5 and 6), if the price suits Yu |
| RS-12 | Family 1: PLACE markets in recent data, and a V9/market-type change. First, a count of PLACE markets in the lab's year (counts only) | Yu under D-5; Nuance implements and counts | V9 and the live rules refuse PLACE (R:validate.py:114-117; R:config.py:63) | Ask for the count now; decide after families 2 and 5 report |
| RS-13 | Lab state for any new real-data run: a new state root, or a reviewed state-gate change | Yu; Nuance | A new C0's L1 refuses with `state_history` (§4) | Ask Nuance for options first |
| RS-14 | Before V9 on real data: U-10, a labelled run without V9, or Yu's D-5 ruling. Then U-1, or the indicative figure, for P&L | Nuance; Yu for D-5 | 0 of 12,208 markets carry the ladder field; P&L leaves out 49.5% of markets | Nuance's call on the route |
| RS-15 | A review gate for agent-written code before live; the live code hash equals the pre-registered hash | Yu decides; Astra reviews | A strategy that trades by itself must be the one that was tested | Yes |
| RS-16 | Pilot budget: the £499 key plus a total loss limit of £X; reaching it stops the pilot for a review | Yu | At £20 stakes luck alone can swing £1,000-2,000 over 1,000 bets (§2) | £500-1,000, set before buying the key (G1) |
| RS-17 | Bot bets and Yu's own bets on one account | Yu; Nuance | Yu said "bet angel never used" (2026-10-15), but any manual bets share commission netting, caps and the Expert Fee test | The bot stays out of markets Yu trades, or attribution rules |
| RS-18 | Delayed-key plumbing check; live at small stakes as the forward test; G1 checks before buying the key (ask Betfair support, set a loss limit) | Yu; Nuance | The delayed key cannot reproduce pre-off fills | Decide after a pass on recent data |
| RS-19 | Upstream live-automation policy, plus a strategy order source, a long-lived session and §3's safeguards (S:DESIGN P-2..P-5, P-11) | Yu approves in writing (R:docs/betfair-order-path.md:630). Lab-Claude's proposal: Nuance drafts and Astra reviews, as for L4 (S:DESIGN 12) | Research AGENTS.md:10 allows only orders "the operator types at a terminal"; the gateway refuses `source="api"` live (R:gateway.py:863) | Defer until a pass on recent data |
| RS-20 | Live pilot caps, in Nuance's config on the Air: £20 stake per order, £20 worst-case loss per order, £40 per market, £150 across markets, £200 daily loss (the ceiling); order-rate caps unchanged (200 orders a day). All within the hard ceilings (£50, £100, £200, £500, £200; R:constants.py:197-217), so a setting change, not code | Yu sets the stake ("we can do £20"); Nuance sets the config when the pilot starts | A £20 back carries £20 of liability, above today's £10 per-order cap, so the caps must rise together. Liquidity near the off can take £20 in most GB WIN markets; thin niches may part-fill (*Inference*). Yu expects more than 30 bets a day; at 50 £20 bets a day an ordinary day swings about ±£280, so a £100 daily limit would stop many normal days. Above £200 needs a code change (*Inference*) | Yes, from the pilot's start; nothing changes before then |
| RS-21 | Counts from the lab's 2015-16 PRO files: in-play `betDelay` values and `betDelayModels` for GB/IE WIN markets (counts only) | Nuance | Family 6 depends on how long the delay is and whether resting orders skip it | Ask now |

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

Repository sources, read-only on 2026-10-19: betangel-research main 0d32421 (R:; bare `.py` names are in `betangel_research/betfair/`, or its `backtest/` for cohort, contract and trial_ledger), and commit 416702f (research PR #28) for the runbook L1 change; betangel-suite r4-viewing 52a9edc (S:; `rx.py` is in `betangel_suite/`); proposal 001 (`docs/proposals/001-agent-seat.md`, branch proposal-001). Nuance's note of 2026-10-19 is lab inbox `20261019T102907Z-air.md`; Yu's 2026-10-15 words are recorded in lab outbox `20261015T135837Z-lab-suite-rulings.md`. Working notes: `round6/rescope/market-facts.md` and `round6/rescope/code-inventory.md` in lab-Claude's session scratchpad.
