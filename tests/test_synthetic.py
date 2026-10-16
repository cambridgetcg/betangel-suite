"""betangel_suite.synthetic: the synthetic PRO market generator (DESIGN.md 5.6, 6.7, 11; docs/data-handling.md).

Determinism (on python3.13 and python3.11 alike), the reserved namespace (tools/hygiene_scan.py passes on the
generated text and catches a planted non-reserved id in it), every message accepted by upstream's MarketBookCache
with valid snapshots before the off, ladders that look like a market (tick ladder, pence, depth, spread, trades),
sizes in the real ranges of DESIGN.md 6.7, the in-play flip, CLOSED with a winner, and each Phase 0b option.
Everything is generated in memory or into temp dirs under TMPDIR; nothing here reads a data root.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from unittest import mock

from betangel_suite import rx, synthetic
from betangel_suite.synthetic import Spec, generate
from tests import ARM_ENGINE, FORBID, ROOT, child_env, make_home, rmtree

SMALL = {"runners": 6, "pre_off_s": 120, "inplay_s": 20}
SCANNER = os.path.join(ROOT, "tools", "hygiene_scan.py")
OTHER_PYTHON = {(3, 13): "/opt/homebrew/bin/python3.11", (3, 11): "/opt/homebrew/bin/python3.13"}
CHUNK_BYTES = 400_000           # below the scanner's 512 KiB content limit
COUNTERS_ZERO = ("settlement_zeroing_seen", "duplicate_definition_dropped", "deltas_dropped_while_not_open",
                 "handicap_runners_omitted", "ladder_prefix_truncations", "stream_unreliable_seen")


def _j(*parts):
    return "".join(parts)


def digest(market):
    found = hashlib.sha256()
    for line in market.lines():
        found.update(line + b"\n")
    return found.hexdigest()


def replay(market, *, every=1):
    """([(message, snapshot or None)], cache): every message applied, a snapshot after every every-th message
    and after every message that carries a definition (every=0: definitions only)."""
    cache = rx.book.MarketBookCache(key_type="historical", app_key_slot=None, source="recording")
    found = []
    for index, message in enumerate(market.messages()):
        cache.apply(message)
        take = "marketDefinition" in message["mc"][0] or (every and index % every == 0)
        found.append((message, cache.snapshot(market.market_id) if take else None))
    return found, cache


def snapshots_at(market, seconds_before_off):
    """{s: the snapshot after the last message published before T - s} for each s."""
    cache = rx.book.MarketBookCache(key_type="historical", app_key_slot=None, source="recording")
    marks = sorted(seconds_before_off, reverse=True)
    found = {}
    for message in market.messages():
        while marks and message["pt"] >= market.off_pt - marks[0] * 1000:
            found[marks.pop(0)] = cache.snapshot(market.market_id)
        cache.apply(message)
    return found


def definitions(market):
    """[(pt, marketDefinition, img)] in file order."""
    return [(m["pt"], m["mc"][0]["marketDefinition"], m["mc"][0].get("img") is True)
            for m in market.messages() if "marketDefinition" in m["mc"][0]]


def touch(snapshot):
    """{selection id: (best back hundredths, best lay hundredths)} for runners quoted on both sides."""
    return {sel: (rx.ticks.to_hundredths(r["back"][0][0]), rx.ticks.to_hundredths(r["lay"][0][0]))
            for sel, r in snapshot["runners"].items() if r["back"] and r["lay"]}


def book_entries(snapshot):
    return sum(len(r["back"]) + len(r["lay"]) + len(r["traded"] or {}) for r in snapshot["runners"].values())


class NamespaceTests(unittest.TestCase):

    def test_ids_names_and_venue_are_reserved(self):
        for spec in (Spec(seed=0, runners=2), Spec(seed=1), Spec(seed=999_999, runners=44),
                     Spec(seed=123_456_789, runners=60)):
            market = generate(spec)
            self.assertTrue(synthetic.is_synthetic_market_id(market.market_id), spec)
            self.assertTrue(synthetic.is_synthetic_event_id(market.event_id), spec)
            self.assertEqual(len(market.selection_ids), spec.runners)
            self.assertEqual(len(set(market.selection_ids)), spec.runners)
            self.assertTrue(all(synthetic.is_synthetic_selection_id(sel) for sel in market.selection_ids))
            self.assertEqual(market.runner_names, tuple("Synthetic %d" % (i + 1) for i in range(spec.runners)))
            self.assertEqual(market.venue, "Synthetic Park")
            self.assertTrue(market.market_name.startswith("Synthetic "))
            self.assertTrue(market.event_name.startswith("Synthetic Park "))
        self.assertEqual(generate(Spec(seed=1_234_567)).market_id, _j("1.999", "234567"))
        self.assertEqual(generate(Spec(seed=1_234_567)).event_id, _j("99", "234567"))

    def test_namespace_predicates(self):
        self.assertTrue(synthetic.is_synthetic_market_id(_j("1.999", "000101")))
        for value in (_j("1.1", "1876", "5432"), _j("1.999", "12345"), _j("1.999", "1234567"), _j("2.999", "000101"),
                      1.999000101, None):
            self.assertFalse(synthetic.is_synthetic_market_id(value), value)
        self.assertTrue(synthetic.is_synthetic_event_id(_j("99", "000101")))
        for value in (_j("2745", "6789"), _j("99", "00010"), int(_j("99", "000101"))):
            self.assertFalse(synthetic.is_synthetic_event_id(value), value)
        self.assertTrue(synthetic.is_synthetic_selection_id(int(_j("9", "1234567"))))
        for value in (int(_j("1234", "5678")), int(_j("9", "123456")), int(_j("9", "1234", "5678")), True,
                      _j("9", "1234567"), 91234567.0):
            self.assertFalse(synthetic.is_synthetic_selection_id(value), value)

    def test_every_message_stays_in_the_namespace(self):
        market = generate(Spec(seed=5, options={"suspension", "removal", "nonfinite_sp"}, **SMALL))
        selections = set(market.selection_ids)
        for message in market.messages():
            self.assertEqual(len(message["mc"]), 1)
            change = message["mc"][0]
            self.assertEqual(change["id"], market.market_id)
            self.assertLessEqual({rc["id"] for rc in change.get("rc", ())}, selections)
            md = change.get("marketDefinition")
            if md is not None:
                self.assertEqual((md["eventId"], md["venue"], md["eventTypeId"]), (market.event_id, "Synthetic Park", "7"))
                self.assertEqual(tuple(r["id"] for r in md["runners"]), market.selection_ids)
                self.assertEqual(tuple(r["name"] for r in md["runners"]), market.runner_names)
                self.assertEqual((md["name"], md["eventName"]), (market.market_name, market.event_name))

    def test_hygiene_scanner_passes_on_generated_text(self):
        specs = (Spec(seed=21, runners=44, pre_off_s=300, inplay_s=30),
                 Spec(seed=22, options={"suspension", "removal", "nonfinite_sp"}, **SMALL),
                 Spec(seed=23, options={"no_market_time", "month:2026-10"}, **SMALL),
                 Spec(seed=24, runners=12, pre_off_s=1800, inplay_s=60))
        folder = tempfile.mkdtemp(prefix="synthetic-scan-")
        self.addCleanup(rmtree, folder)
        names, chunk, first_rc_line = [], [], None

        def flush():
            name = "stream-%03d.txt" % len(names)
            with open(os.path.join(folder, name), "xb") as handle:
                handle.write(b"".join(chunk))
            names.append(name)
            chunk.clear()

        for spec in specs:
            for line in generate(spec).lines():
                if sum(map(len, chunk)) + len(line) + 1 > CHUNK_BYTES:
                    flush()
                chunk.append(line + b"\n")
                if first_rc_line is None and b'"atb":[[' in line and b"marketDefinition" not in line:
                    first_rc_line = line
        flush()
        code, output = self.scan(folder, names)
        self.assertEqual(code, 0, output)
        self.assertIn("hygiene_scan: OK %d file(s) scanned" % len(names), output)
        # Control: the same kind of line with a selection id outside the reserved namespace is caught.
        message = json.loads(first_rc_line)
        planted = int(_j("1234", "5678"))
        message["mc"][0]["rc"][0]["id"] = planted
        with open(os.path.join(folder, "control.txt"), "x", encoding="ascii") as handle:
            handle.write(json.dumps(message, separators=(",", ":")) + "\n")
        code, output = self.scan(folder, ["control.txt"])
        self.assertEqual(code, 1, output)
        self.assertIn("stream_record", output)
        self.assertNotIn(str(planted), output)

    def scan(self, folder, names):
        env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "LANG": "en_GB.UTF-8",
               "TMPDIR": os.environ["TMPDIR"], FORBID: "1"}
        result = subprocess.run([sys.executable, "-I", "-S", "-B", SCANNER, "--root", folder, *names], env=env,
                                cwd=folder, capture_output=True, text=True, timeout=300)
        return result.returncode, result.stdout + result.stderr


class DeterminismTests(unittest.TestCase):

    def test_equal_specs_give_equal_markets_and_bytes(self):
        spec = Spec(seed=7, runners=7, pre_off_s=200, inplay_s=30, options={"removal", "suspension"})
        again = Spec(seed=7, runners=7, pre_off_s=200, inplay_s=30, options=["suspension", "removal"])
        self.assertEqual(spec, again)
        self.assertIsInstance(again.options, frozenset)
        first, second = generate(spec), generate(again)
        self.assertEqual(first, second)
        self.assertEqual(digest(first), digest(second))
        self.assertEqual(list(first.lines()), list(first.lines()))

    def test_messages_are_the_parsed_lines(self):
        market = generate(Spec(seed=8, **SMALL))
        self.assertEqual(list(market.messages()), [json.loads(line) for line in market.lines()])

    def test_different_seeds_differ(self):
        one, two = generate(Spec(seed=9, **SMALL)), generate(Spec(seed=10, **SMALL))
        self.assertNotEqual(one.market_id, two.market_id)
        self.assertNotEqual(one.selection_ids, two.selection_ids)
        self.assertNotEqual(digest(one), digest(two))

    def test_same_bytes_on_the_other_interpreter(self):
        other = OTHER_PYTHON.get(tuple(sys.version_info[:2]))
        if other is None or not os.path.exists(other):
            self.skipTest("the other supported interpreter is not installed")
        specs = (dict(seed=11, runners=6, pre_off_s=90, inplay_s=15),
                 dict(seed=12, runners=9, pre_off_s=120, inplay_s=20,
                      options=["suspension", "removal", "nonfinite_sp", "month:2015-05"]))
        code = ARM_ENGINE + (
            "import hashlib, json\n"
            "from betangel_suite import synthetic\n"
            "found = []\n"
            "for kwargs in %r:\n"
            "    digest = hashlib.sha256()\n"
            "    for line in synthetic.generate(synthetic.Spec(**kwargs)).lines():\n"
            "        digest.update(line + b'\\n')\n"
            "    found.append(digest.hexdigest())\n"
            "print(json.dumps(found))\n") % (specs,)
        home = make_home(self, deps=True)
        result = subprocess.run([other, "-I", "-S", "-B", "-c", code], env=child_env(home), cwd=home,
                                capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertEqual(json.loads(result.stdout), [digest(generate(Spec(**kwargs))) for kwargs in specs])


class StreamTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.market = generate(Spec(seed=31))
        cls.lines = list(cls.market.lines())
        cls.messages = [rx.receipts.strict_json_loads(line) for line in cls.lines]   # no NaN, no duplicate keys

    def test_pro_historical_stream_shape(self):
        market = self.market
        previous = None
        same_pt = 0
        for line, message in zip(self.lines, self.messages):
            self.assertNotIn(b"\n", line)
            line.decode("ascii")
            self.assertEqual(message["op"], "mcm")
            self.assertTrue(message["clk"].isdigit() and len(message["clk"]) == 10)
            self.assertIs(type(message["pt"]), int)
            if previous is not None:
                self.assertGreaterEqual(message["pt"], previous)
                same_pt += message["pt"] == previous
            previous = message["pt"]
            self.assertEqual(len(message["mc"]), 1)
            self.assertIn(message["mc"][0].get("img", True), (True,))
        self.assertEqual((self.messages[0]["pt"], self.messages[-1]["pt"]), (market.start_pt, market.close_pt))
        self.assertEqual(market.start_pt, market.off_pt - 600_000)
        self.assertEqual(market.off_pt, market.market_time_ms)
        self.assertGreater(same_pt, 0)                              # some messages share a pt batch
        self.assertLess(max(map(len, self.lines)), 1 << 20)         # the suite's per-line limit (DESIGN.md 5.4)

    def test_prices_on_the_tick_ladder_and_sizes_in_pence(self):
        checked = 0
        for message in self.messages:
            for rc in message["mc"][0].get("rc", ()):
                for field in ("atb", "atl", "trd", "spb", "spl"):
                    for price, size in rc.get(field, ()):
                        self.assertTrue(rx.ticks.is_on_ladder(rx.ticks.to_hundredths(price)), price)
                        self.assertGreaterEqual(rx.ticks.to_pence(size), 0)
                        checked += 1
                if "ltp" in rc:
                    self.assertTrue(rx.ticks.is_on_ladder(rx.ticks.to_hundredths(rc["ltp"])))
                if "tv" in rc:
                    self.assertGreaterEqual(rx.ticks.to_pence(rc["tv"]), 0)
                for field in ("spn", "spf"):
                    if field in rc:
                        self.assertIsInstance(rc[field], float)
                        self.assertGreaterEqual(rc[field], 1.01)
        self.assertGreater(checked, 10_000)

    def test_traded_volume_only_grows_and_tv_is_its_sum(self):
        traded = {}
        trades = 0
        for message in self.messages:
            for rc in message["mc"][0].get("rc", ()):
                ladder = traded.setdefault(rc["id"], {})
                for price, size in rc.get("trd", ()):
                    pence = rx.ticks.to_pence(size)
                    self.assertGreaterEqual(pence, ladder.get(price, 0))
                    ladder[price] = pence
                    trades += 1
                if "tv" in rc:
                    self.assertEqual(rx.ticks.to_pence(rc["tv"]), sum(ladder.values()))
                    self.assertLess(rx.ticks.to_pence(rc["tv"]), synthetic.TV_CAP_P + 1)
        self.assertGreater(trades, 1000)


class TradedBasisTests(unittest.TestCase):
    """trd and tv on the PRO historical basis, backer's stake x 2 (F60), as upstream paper and the engine read them
    (Nuance's PR #4 review, item 1)."""

    def test_a_trade_adds_twice_the_stake_it_takes_to_trd_and_tv(self):
        real = synthetic._Simulation._trade
        seen = []

        def spy(sim, r, field, index, size):
            level, trd, tv = getattr(r, field).get(index, 0), r.trd.get(index, 0), r.tv
            done = real(sim, r, field, index, size)
            seen.append((done, level - getattr(r, field).get(index, 0), r.trd.get(index, 0) - trd, r.tv - tv))
            return done

        with mock.patch.object(synthetic._Simulation, "_trade", spy):
            for _line in generate(Spec(seed=48, options={"suspension", "removal"}, **SMALL)).lines():
                pass
        trades = [entry[1:] for entry in seen if entry[0]]
        self.assertGreater(len(trades), 100)
        for taken, trd_added, tv_added in trades:
            self.assertGreater(taken, 0)
            self.assertEqual((trd_added, tv_added), (2 * taken, 2 * taken))
        self.assertEqual({entry[1:] for entry in seen if not entry[0]} - {(0, 0, 0)}, set())

    def test_the_volume_cap_counts_the_doubled_stake(self):
        sim = synthetic._Simulation(generate(Spec(seed=49, **SMALL)))
        r, index = sim.runners[0], 100
        r.atb[index] = 10_00
        r.tv = synthetic.TV_CAP_P - 5                       # room for 2 pence of stake, counted as 4
        self.assertTrue(sim._trade(r, "atb", index, 10_00))
        self.assertEqual((r.atb[index], r.tv), (10_00 - 2, synthetic.TV_CAP_P - 1))
        self.assertFalse(sim._trade(r, "atb", index, 10_00))   # no room for a whole doubled penny
        self.assertEqual((r.atb[index], r.tv), (10_00 - 2, synthetic.TV_CAP_P - 1))


class BookTests(unittest.TestCase):

    def test_every_message_applies_and_every_snapshot_before_the_off_is_valid(self):
        for spec in (Spec(seed=41, **SMALL), Spec(seed=42, runners=3, pre_off_s=60, inplay_s=10),
                     Spec(seed=43, runners=20, pre_off_s=90, inplay_s=15)):
            market = generate(spec)
            found, cache = replay(market)
            pre = [snapshot for message, snapshot in found if message["pt"] < market.off_pt]
            self.assertGreater(len(pre), 100)
            for snapshot in pre:
                rx.schemas.validate_book_snapshot(snapshot)
                self.assertEqual((snapshot["status"], snapshot["inplay"], snapshot["invalid_reason"]),
                                 ("OPEN", False, None))
                self.assertEqual(snapshot["market_time"], market.market_time)
                self.assertEqual(snapshot["price_ladder_type"], "CLASSIC")
                self.assertEqual(set(snapshot["runners"]), {str(sel) for sel in market.selection_ids})
                self.assertEqual(len(touch(snapshot)), spec.runners)    # every runner quoted both sides
                for back, lay in touch(snapshot).values():
                    self.assertLess(back, lay)                          # never crossed
            # In play from exactly the off: the generator's fixed flip shape (unverified; DESIGN.md 11.1).
            in_play = [snapshot for message, snapshot in found if market.off_pt <= message["pt"] < market.suspend_pt]
            for snapshot in in_play:
                self.assertEqual((snapshot["status"], snapshot["inplay"], snapshot["invalid_reason"]),
                                 ("OPEN", True, None))
                for back, lay in touch(snapshot).values():
                    self.assertLess(back, lay)
            self.assertEqual({key: cache.counters[key] for key in COUNTERS_ZERO}, dict.fromkeys(COUNTERS_ZERO, 0))
            self.assertEqual(cache.counters["non_finite_seen"], 0)

    def test_ladders_look_like_a_market_near_the_off(self):
        for seed in (44, 45, 46):
            market = generate(Spec(seed=seed))
            snapshot = snapshots_at(market, (1,))[1]
            prices = touch(snapshot)
            for sel, runner in snapshot["runners"].items():
                self.assertGreaterEqual(len(runner["back"]), 3, sel)
                self.assertGreaterEqual(len(runner["lay"]), 3, sel)
                self.assertGreater(runner["total_matched"], 0)
                self.assertIsNotNone(runner["ltp"])
            back_book = sum(100 / back for back, _ in prices.values())
            lay_book = sum(100 / lay for _, lay in prices.values())
            self.assertTrue(1.0 <= back_book <= 1.08, back_book)        # overround on the back side
            self.assertTrue(0.90 <= lay_book <= 1.0, lay_book)
            backs = sorted(back for back, _ in prices.values())
            self.assertGreaterEqual(backs[-1] / backs[0], 3)            # a favourite and outsiders

    def test_spreads_tighten_and_sizes_grow_towards_the_off(self):
        market = generate(Spec(seed=47, runners=12, pre_off_s=3600, inplay_s=20))
        snaps = snapshots_at(market, (3500, 30))

        def mean_spread(snapshot):
            pairs = touch(snapshot).values()
            return sum(rx.ticks.ticks_between(back, lay) for back, lay in pairs) / len(pairs)

        def mean_best_size(snapshot):
            sizes = [r["back"][0][1] + r["lay"][0][1] for r in snapshot["runners"].values()]
            return sum(sizes) / len(sizes)

        self.assertGreater(mean_spread(snaps[3500]), mean_spread(snaps[30]) + 0.5)
        self.assertGreater(mean_best_size(snaps[30]), 2 * mean_best_size(snaps[3500]))

    def test_trades_move_ltp_and_volume(self):
        market = generate(Spec(seed=48, **SMALL))
        ltps, volumes = {}, {}
        for message in market.messages():
            if message["pt"] >= market.off_pt:
                break
            for rc in message["mc"][0].get("rc", ()):
                if "ltp" in rc:
                    ltps.setdefault(rc["id"], set()).add(rc["ltp"])
                if "tv" in rc:
                    volumes.setdefault(rc["id"], []).append(rc["tv"])
        favourite = market.selection_ids[max(range(SMALL["runners"]), key=lambda i: market.plan.q0[i])]
        self.assertGreaterEqual(len(ltps[favourite]), 3)
        self.assertEqual(set(volumes), set(market.selection_ids))
        self.assertTrue(all(series[-1] > series[0] for series in volumes.values() if len(series) > 1))

    def test_favourite_longshot_bias(self):
        for seed in range(50, 55):
            plan = generate(Spec(seed=seed, runners=12)).plan
            self.assertLess(max(plan.q0) / min(plan.q0), max(plan.true_p) / min(plan.true_p))
            self.assertAlmostEqual(sum(plan.q0), 1.0)

    def test_sizes_reach_the_real_ranges(self):
        # DESIGN.md 6.7 (real aggregates): 5-44 runners and 721-6,166 book entries; 3,309-5,922 messages in the
        # last 10 minutes; 14-25 in the busiest second; files spanning 25-53 h, 53-91% of messages before T-30m.
        entries = {}
        for runners in (5, 44):
            market = generate(Spec(seed=60 + runners, runners=runners))
            entries[runners] = book_entries(snapshots_at(market, (1,))[1])
            pts = [message["pt"] for message in market.messages()]
            last10 = sum(1 for pt in pts if market.off_pt - 600_000 <= pt < market.off_pt)
            self.assertTrue(3000 <= last10 <= 6500, last10)
            busiest = max(Counter(pt // 1000 for pt in pts if pt < market.off_pt).values())
            self.assertTrue(12 <= busiest <= 30, busiest)
        self.assertTrue(400 <= entries[5] <= 1500, entries)
        self.assertTrue(3000 <= entries[44] <= 7000, entries)
        market = generate(Spec(seed=69, runners=5, pre_off_s=26 * 3600, inplay_s=30))
        pts = [message["pt"] for message in market.messages()]
        early = sum(1 for pt in pts if pt < market.off_pt - 1_800_000) / len(pts)
        self.assertTrue(15_000 <= len(pts) <= 80_000, len(pts))
        self.assertTrue(0.5 <= early <= 0.91, early)


class TimelineTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.market = generate(Spec(seed=71, **SMALL))
        cls.found, cls.cache = replay(cls.market, every=5)
        cls.definitions = definitions(cls.market)

    def test_opening_image(self):
        message = self.found[0][0]
        change = message["mc"][0]
        self.assertEqual(message["pt"], self.market.start_pt)
        self.assertIs(change["img"], True)
        md = change["marketDefinition"]
        self.assertEqual((md["status"], md["inPlay"], md["bspReconciled"], md["bspMarket"], md["betDelay"]),
                         ("OPEN", False, False, True, 0))
        self.assertEqual(md["marketTime"], self.market.market_time)
        self.assertEqual({rc["id"] for rc in change["rc"] if rc.get("atb") and rc.get("atl")},
                         set(self.market.selection_ids))

    def test_in_play_flip_at_the_off(self):
        # The generator's fixed flip shape: in play at exactly marketTime, never revised, no SUSPENDED at the off.
        # The real shape is unverified (DESIGN.md 11.1); options for other shapes are owed before Phase 1a.
        flips = [(pt, md) for pt, md, _ in self.definitions if md["inPlay"]]
        pt, md = flips[0]
        self.assertEqual(pt, self.market.off_pt)
        self.assertEqual((md["status"], md["betDelay"], md["bspReconciled"], md["crossMatching"]), ("OPEN", 1, True, False))
        self.assertTrue(all(isinstance(r["bsp"], float) and r["bsp"] >= 1.01 for r in md["runners"]))
        for earlier_pt, earlier, _ in self.definitions:
            if earlier_pt < pt:
                self.assertFalse(earlier["inPlay"])
                self.assertFalse(earlier["bspReconciled"])
                self.assertFalse(any("bsp" in r for r in earlier["runners"]))
        for message, snapshot in self.found:
            if snapshot is not None:
                self.assertEqual(snapshot["inplay"], message["pt"] >= self.market.off_pt)
        flip = next(snapshot for message, snapshot in self.found if message["pt"] == self.market.off_pt)
        for runner in flip["runners"].values():                     # unmatched offers lapsed: thin ladders
            self.assertLessEqual(len(runner["back"]) + len(runner["lay"]), 10)

    def test_closed_with_the_winner(self):
        market = self.market
        (suspend_pt, suspended, _), (close_pt, closed, _) = self.definitions[-2:]
        self.assertEqual((suspend_pt, suspended["status"], suspended["inPlay"]), (market.suspend_pt, "SUSPENDED", True))
        self.assertEqual((close_pt, closed["status"], closed["inPlay"]), (market.close_pt, "CLOSED", True))
        self.assertEqual(self.found[-1][0]["pt"], market.close_pt)
        self.assertEqual(closed["settledTime"], synthetic.iso_ms(market.close_pt))
        statuses = {r["id"]: r["status"] for r in closed["runners"]}
        self.assertEqual([sel for sel, status in statuses.items() if status == "WINNER"], [market.winner_id])
        self.assertEqual(set(statuses.values()), {"WINNER", "LOSER"})
        final = self.found[-1][1]
        self.assertEqual(final["status"], "CLOSED")
        self.assertEqual(final["runners"][str(market.winner_id)]["status"], "WINNER")
        self.assertTrue(all(not r["back"] and not r["lay"] and r["ltp"] is None for r in final["runners"].values()))
        self.assertTrue(all(r["traded"] and r["total_matched"] > 0 for r in final["runners"].values()))

    def test_no_outcome_before_it_is_published(self):
        lines = list(self.market.lines())
        for line in lines[:-1]:
            for needle in (b'"WINNER"', b'"LOSER"', b"settledTime"):
                self.assertNotIn(needle, line)
        for message, line in zip((m for m, _ in self.found), lines):
            if message["pt"] < self.market.off_pt:
                self.assertNotIn(b'"bsp"', line)
                self.assertNotIn(b'"bspReconciled":true', line)

    def test_the_winner_converges_in_play(self):
        for seed in (72, 73, 74, 75):
            market = generate(Spec(seed=seed, **SMALL))
            cache = rx.book.MarketBookCache(key_type="historical", app_key_slot=None, source="recording")
            last = None
            for message in market.messages():
                if message["pt"] >= market.suspend_pt:
                    break
                cache.apply(message)
                last = message
            self.assertGreaterEqual(last["pt"], market.suspend_pt - 2000)
            prices = touch(cache.snapshot(market.market_id))
            winner = prices[str(market.winner_id)][0]
            self.assertEqual(winner, min(back for back, _ in prices.values()), seed)
            self.assertLessEqual(winner, 120, seed)


class OptionTests(unittest.TestCase):

    def assert_pre_off_open_snapshots_valid(self, market, found, allow=()):
        for message, snapshot in found:
            if snapshot is not None and message["pt"] < market.off_pt and snapshot["status"] == "OPEN":
                if message["pt"] not in allow:
                    self.assertIsNone(snapshot["invalid_reason"], message["pt"])

    def test_suspension(self):
        market = generate(Spec(seed=61, options={"suspension"}, **SMALL))
        found, _cache = replay(market)
        defs = definitions(market)
        suspended = [i for i, (_pt, md, _img) in enumerate(defs) if md["status"] == "SUSPENDED" and not md["inPlay"]]
        self.assertEqual(len(suspended), 1)
        at, reopen = market.plan.suspension
        self.assertEqual(defs[suspended[0]][0], at)
        pt, md, img = defs[suspended[0] + 1]
        self.assertEqual((pt, md["status"], img), (reopen, "OPEN", True))
        self.assertGreater(md["version"], defs[suspended[0]][1]["version"])
        during = [snapshot for message, snapshot in found if at <= message["pt"] < reopen]
        self.assertTrue(during)
        for snapshot in during:
            self.assertEqual((snapshot["status"], snapshot["invalid_reason"]), ("SUSPENDED", None))
            self.assertTrue(all(not r["back"] and not r["lay"] for r in snapshot["runners"].values()))
        after = [snapshot for message, snapshot in found if reopen <= message["pt"] < market.off_pt]
        self.assertTrue(after and all(len(touch(s)) == SMALL["runners"] for s in after))
        self.assert_pre_off_open_snapshots_valid(market, found)    # the image clears ladder_partial_after_suspension

    def test_the_removed_runners_adjustment_factor_is_its_chance_at_removal(self):
        # Nuance's PR #4 review, item 4: it used to keep its opening value. Betfair's real semantics are unverified.
        real = synthetic._Simulation._removal_message
        seen = []

        def spy(sim, t):
            r = sim.runners[sim.p.removed]
            expected = round(max(0.01, 100 * sim._q(r)), 2)
            line = real(sim, t)
            seen.append((expected, json.loads(line)["mc"][0]["marketDefinition"]["runners"][r.i]))
            return line

        with mock.patch.object(synthetic._Simulation, "_removal_message", spy):
            for seed in (62, 63, 64):
                for _line in generate(Spec(seed=seed, options={"removal"}, **SMALL)).lines():
                    pass
        self.assertEqual(len(seen), 3)
        for expected, runner in seen:
            self.assertEqual(runner["status"], "REMOVED")
            self.assertEqual(runner["adjustmentFactor"], expected)

    def test_removal(self):
        market = generate(Spec(seed=62, options={"removal"}, **SMALL))
        (removed,) = market.removed_ids
        self.assertNotEqual(removed, market.winner_id)
        index = market.selection_ids.index(removed)
        self.assertNotEqual(market.plan.q0[index], max(market.plan.q0))     # never the favourite
        found, _cache = replay(market)
        defs = definitions(market)
        at, reopen = market.plan.removal
        position = next(i for i, (pt, _md, _img) in enumerate(defs) if pt == at)
        _pt, md, _img = defs[position]
        runner = md["runners"][index]
        self.assertEqual(md["status"], "SUSPENDED")
        self.assertEqual((runner["status"], runner["removalDate"]), ("REMOVED", synthetic.iso_ms(at)))
        self.assertIsInstance(runner["adjustmentFactor"], float)
        self.assertEqual(md["numberOfActiveRunners"], SMALL["runners"] - 1)
        others = sum(r["adjustmentFactor"] for r in md["runners"] if r["status"] == "ACTIVE")
        self.assertAlmostEqual(others, 100.0, delta=0.5)
        self.assertNotEqual(runner["adjustmentFactor"], round(100 * market.plan.q0[index], 2))   # not the opening one
        self.assertEqual((defs[position + 1][0], defs[position + 1][1]["status"], defs[position + 1][2]),
                         (reopen, "OPEN", True))
        for pt, later, _img in defs[position:]:
            self.assertEqual(later["runners"][index]["status"], "REMOVED")
            self.assertNotIn("bsp", later["runners"][index])
        for message, snapshot in found:
            if snapshot is not None and message["pt"] >= at:
                entry = snapshot["runners"][str(removed)]
                self.assertEqual((entry["status"], entry["back"], entry["lay"], entry["ltp"]), ("REMOVED", [], [], None))
        self.assert_pre_off_open_snapshots_valid(market, found)

    def test_nonfinite_sp(self):
        market = generate(Spec(seed=63, options={"nonfinite_sp"}, **SMALL))
        start, end, who = market.plan.nonfinite
        lines = list(market.lines())
        marked = [line for line in lines if b'"spn":"NaN"' in line]
        self.assertEqual(len(marked), 1)
        self.assertIn(b'"spf":"Infinity"', marked[0])
        self.assertIn(b'"spl":[[1000,"Infinity"]]', marked[0])
        self.assertEqual(sum(b'"spl":[[1000,0]]' in line for line in lines), 1)
        for line in lines:
            rx.receipts.strict_json_loads(line)                       # quoted strings, never bare NaN or Infinity
        found, cache = replay(market)
        self.assertEqual(cache.counters["non_finite_seen"], 1)
        window = 0
        for message, snapshot in found:
            if message["pt"] < market.off_pt:
                expected = "non_finite_size" if start <= message["pt"] < end else None
                self.assertEqual(snapshot["invalid_reason"], expected, message["pt"])
                window += expected is not None
        self.assertGreater(window, 10)
        self.assertEqual(market.selection_ids[who], json.loads(marked[0])["mc"][0]["rc"][0]["id"])

    def test_no_market_time(self):
        market = generate(Spec(seed=64, options={"no_market_time"}, **SMALL))
        self.assertIsNone(market.market_time)
        self.assertIs(type(market.market_time_ms), int)
        for _pt, md, _img in definitions(market):
            self.assertFalse({"marketTime", "suspendTime", "openDate"} & set(md))
        found, _cache = replay(market, every=20)
        self.assertTrue(all(s["market_time"] is None for _m, s in found if s is not None))
        self.assert_pre_off_open_snapshots_valid(market, found)

    def test_month_override(self):
        market = generate(Spec(seed=65, options={"month:2026-01"}, **SMALL))
        self.assertEqual(market.market_time, "2026-01-01T14:00:00.000Z")
        self.assertEqual(market.month, "2026-01")
        self.assertEqual({md["marketTime"] for _pt, md, _img in definitions(market)}, {market.market_time})
        self.assertEqual(rx.archive.market_month(market.market_time), "2026-01")
        self.assertEqual(rx.archive.month_gate(market.month), "month_sealed_holdout")
        moved = generate(Spec(seed=66, market_time="2015-06-30T19:45:00.000Z", options={"month:2015-05"}, **SMALL))
        self.assertEqual(moved.market_time, "2015-05-30T19:45:00.000Z")
        self.assertIsNone(rx.archive.month_gate(moved.month))
        with self.assertRaises(ValueError):
            Spec(seed=67, market_time="2015-01-31T14:00:00.000Z", options={"month:2015-02"})

    def test_options_combine(self):
        options = {"suspension", "removal", "nonfinite_sp", "month:2015-07"}
        market = generate(Spec(seed=68, runners=10, pre_off_s=300, inplay_s=30, options=options))
        plan = market.plan
        self.assertLess(plan.suspension[1], plan.removal[0])
        self.assertLess(plan.removal[1], plan.nonfinite[0])
        self.assertLess(plan.nonfinite[1], market.off_pt)
        found, cache = replay(market, every=3)
        window = {message["pt"] for message, _s in found if plan.nonfinite[0] <= message["pt"] <= plan.nonfinite[1]}
        self.assert_pre_off_open_snapshots_valid(market, found, allow=window)
        self.assertEqual(found[-1][1]["status"], "CLOSED")
        self.assertEqual(market.month, "2015-07")

    def test_invalid_specs_are_refused(self):
        bad = ({"seed": -1}, {"seed": True}, {"seed": 1.0}, {"seed": 1, "runners": 1}, {"seed": 1, "runners": 61},
               {"seed": 1, "pre_off_s": 29}, {"seed": 1, "pre_off_s": 3 * 86_400 + 1}, {"seed": 1, "inplay_s": 9},
               {"seed": 1, "options": {"late_off"}}, {"seed": 1, "options": "removal"},
               {"seed": 1, "options": {"month:2026-13"}}, {"seed": 1, "options": {"month:2026-01", "month:2026-02"}},
               {"seed": 1, "options": {1}}, {"seed": 1, "options": 5}, {"seed": 1, "runners": 2, "options": {"removal"}},
               {"seed": 1, "market_time": "2015-06-01T14:00:00Z"}, {"seed": 1, "market_time": "2015-06-01T14:00:00.000+01:00"},
               {"seed": 1, "market_time": "2015-02-30T14:00:00.000Z"}, {"seed": 1, "market_time": None},
               {"seed": 1, "market_time": "1970-01-01T00:05:00.000Z"})
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Spec(**kwargs)
        with self.assertRaises(TypeError):
            generate({"seed": 1})


if __name__ == "__main__":
    unittest.main()
