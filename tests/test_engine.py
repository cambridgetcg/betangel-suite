"""The Phase 0b engine (betangel_suite/engine.py; DESIGN.md 6.1, 6.5, 6.8): clock, frames, synthetic-only.

These tests run the actor in this process with a fake wall clock, so time moves only when a test moves
it. Markets come from betangel_suite.synthetic, sized down (5 runners, 2 minutes before the off) to keep the
tier fast; every frame is compared with a reference book.MarketBookCache fed the same messages.
"""

import copy
import os
import threading
import unittest
from unittest import mock

from betangel_suite import config, engine, rx, runmarker, synthetic
from betangel_suite.errors import SuiteError
from tests import make_home, require_no_run_marker

START_NS = 5_000_000_000_000


class FakeClock:

    def __init__(self):
        self.ns = START_NS

    def __call__(self):
        return self.ns

    def advance_ms(self, ms):
        self.ns += ms * 1_000_000


class SmallSynthetic:
    """synthetic with a smaller default Spec; generate and the namespace check are the real ones."""

    is_synthetic_market_id = staticmethod(synthetic.is_synthetic_market_id)
    generate = staticmethod(synthetic.generate)

    @staticmethod
    def Spec(seed):
        return synthetic.Spec(seed=seed, runners=5, pre_off_s=120, inplay_s=20)


class NotSynthetic(SmallSynthetic):
    """The same markets, but the namespace check says no (the engine must refuse)."""

    is_synthetic_market_id = staticmethod(lambda value: False)


def messages(seed):
    return list(synthetic.generate(SmallSynthetic.Spec(seed)).messages())


def reference(seed, upto_pt):
    """(market id, snapshot) after applying every message with pt <= upto_pt, as the oracle would."""
    cache = rx.book.MarketBookCache(key_type="historical", app_key_slot=None, source="recording")
    market_id = None
    for message in messages(seed):
        if message["pt"] > upto_pt:
            break
        cache.apply(message)
        market_id = market_id or message["mc"][0]["id"]
    return market_id, cache.snapshot(market_id, unreliable_ok=True)


def floats_in(value):
    if isinstance(value, float):
        return 1
    if isinstance(value, dict):
        return sum(floats_in(item) for item in value.values())
    if isinstance(value, list):
        return sum(floats_in(item) for item in value)
    return 0


class EngineCase(unittest.TestCase):

    def make(self, cfg=None, synthetic_module=SmallSynthetic, marker=None, grace_s=30, tick_s=engine.TICK_S):
        require_no_run_marker()             # the actor below watches only its temporary HOME's marker
        self.home = make_home(self)
        self.clock = FakeClock()
        self.marker = marker or runmarker.marker_path(None, self.home)
        actor = engine.Engine(cfg or dict(config.DEFAULTS), marker_path=self.marker, synthetic=synthetic_module,
                              clock_ns=self.clock, tick_s=tick_s, marker_grace_s=grace_s)
        actor.start()
        self.addCleanup(self._stop, actor)
        return actor

    @staticmethod
    def _stop(actor):
        actor.stop()
        actor.stopped.wait(5)

    def frame(self, actor, after=0, predicate=None, timeout=5.0, step_ms=0):
        """The next published frame after seq `after` that satisfies predicate; step_ms moves the fake clock
        on each wait (a paused clock needs it to pass the frame-rate limit)."""
        seq = after
        for _ in range(50):
            published, ended = actor.wait(seq, timeout / 50)
            if published is not None:
                seq = published.seq
                if predicate is None or predicate(published.frame):
                    return published
            elif ended is not None:
                self.fail("engine ended: " + ended)
            self.clock.advance_ms(step_ms)
        self.fail("no matching frame")

    def open_and_play(self, actor, seed=21):
        self.assertEqual(actor.command("open_market", {"seed": seed}), {"ok": True, "market_id": "1.9990000%02d" % seed})
        first = self.frame(actor)
        actor.set_watched(True)
        self.assertEqual(actor.command("play", {}), {"ok": True})
        return first


class ConstructionTests(unittest.TestCase):

    def test_refuses_any_configured_data_root(self):
        cfg = dict(config.DEFAULTS, data_roots=["~/betangel-data/historic-pro"])
        with self.assertRaises(SuiteError) as caught:
            engine.Engine(cfg, marker_path="/nonexistent/ACTIVE")
        self.assertEqual(caught.exception.code, "synthetic_only")

    def test_frame_rate_comes_from_the_config(self):
        for value in (4, 21, "10", None, 10.0):
            with self.assertRaises(SuiteError, msg=value):
                engine.Engine(dict(config.DEFAULTS, frame_hz=value), marker_path="/nonexistent/ACTIVE")
        self.assertEqual(engine.Engine(dict(config.DEFAULTS, frame_hz=20), marker_path="/x/ACTIVE").frame_hz, 20)


class CommandTests(EngineCase):

    def test_commands_before_and_after_a_market(self):
        actor = self.make()
        self.assertEqual(actor.command("play", {}), {"ok": False, "code": "no_market"})
        self.assertEqual(actor.command("pause", {}), {"ok": False, "code": "no_market"})
        self.assertEqual(actor.command("stop", {}), {"ok": True})
        self.assertEqual(actor.command("place", {}), {"ok": False, "code": "not_implemented"})
        for bad in ({"speed_x100": 150}, {"speed_x100": "100"}, {"speed_x100": True}, {}):
            self.assertEqual(actor.command("set_speed", bad), {"ok": False, "code": "bad_args"}, bad)
        for speed in engine.SPEEDS_X100:
            self.assertEqual(actor.command("set_speed", {"speed_x100": speed}), {"ok": True})
        for bad in ({"seed": -1}, {"seed": 2 ** 31}, {"seed": True}, {"seed": "1"}, {}):
            self.assertEqual(actor.command("open_market", bad), {"ok": False, "code": "bad_args"}, bad)
        self.assertEqual(actor.command("open_market", {"seed": 3}), {"ok": True, "market_id": "1.999000003"})
        self.assertEqual(actor.command("play", {}), {"ok": False, "code": "not_watched"})
        actor.set_watched(True)
        self.assertEqual(actor.command("play", {}), {"ok": True})
        self.assertEqual(actor.command("pause", {}), {"ok": True})

    def test_non_synthetic_markets_are_refused(self):
        actor = self.make(synthetic_module=NotSynthetic)
        self.assertEqual(actor.command("open_market", {"seed": 3}), {"ok": False, "code": "not_synthetic"})
        self.assertIsNone(actor.latest())

    def test_a_foreign_market_change_id_is_refused(self):
        foreign = "1." + "2" + "3" * 8         # built at run time: outside the reserved namespace

        class Foreign(SmallSynthetic):
            @staticmethod
            def generate(spec):
                market = synthetic.generate(spec)

                class Wrapped:
                    market_id = market.market_id
                    selection_ids = market.selection_ids
                    runner_names = market.runner_names
                    market_time_ms = market.market_time_ms

                    @staticmethod
                    def messages():
                        for index, message in enumerate(market.messages()):
                            if index == 5:
                                message["mc"][0]["id"] = foreign
                            yield message
                return Wrapped

        actor = self.make(synthetic_module=Foreign)
        self.assertEqual(actor.command("open_market", {"seed": 3}), {"ok": False, "code": "not_synthetic"})

    def test_stopped_engine_refuses_commands(self):
        actor = self.make()
        actor.stop()
        self.assertTrue(actor.stopped.wait(5))
        self.assertEqual(actor.ended(), "stopped")
        self.assertEqual(actor.command("play", {}), {"ok": False, "code": "engine_stopping"})
        self.assertEqual(actor.wait(0, 0.1), (None, "stopped"))


class BusyTests(EngineCase):
    """engine_busy is the truth: a command answered engine_busy has not run and never will, and one the actor
    has started returns its real result however long it takes (a nonce caches that answer; 9.2 item 7)."""

    def test_a_command_taken_back_after_its_timeout_never_runs(self):
        entered, release, generated = threading.Event(), threading.Event(), []

        class Slow(SmallSynthetic):
            @staticmethod
            def generate(spec):
                generated.append(spec.seed)
                if spec.seed == 1:                  # holds the actor, so the next command waits in the queue
                    entered.set()
                    release.wait(5)
                return synthetic.generate(spec)

        actor = self.make(synthetic_module=Slow)
        self.addCleanup(release.set)
        first = []
        holder = threading.Thread(target=lambda: first.append(actor.command("open_market", {"seed": 1})))
        holder.start()
        self.assertTrue(entered.wait(5))
        self.assertEqual(actor.command("open_market", {"seed": 2}, timeout=0.05), {"ok": False, "code": "engine_busy"})
        release.set()
        holder.join(5)
        self.assertEqual(first, [{"ok": True, "market_id": "1.999000001"}])
        self.assertEqual(actor.command("pause", {}), {"ok": True})         # queued behind the one taken back
        self.assertEqual(generated, [1])
        self.assertEqual(self.frame(actor).frame["market"]["id"], "1.999000001")

    def test_a_command_the_actor_took_as_its_caller_timed_out_returns_its_result(self):
        actor_took, caller_tried = threading.Event(), threading.Event()
        real_take = engine._Reply.take

        def take(reply):        # orders the race: the actor takes the command, then its caller's timeout ends
            if threading.current_thread().name == "suite-actor":
                taken = real_take(reply)
                actor_took.set()
                return taken
            actor_took.wait(5)
            taken = real_take(reply)
            caller_tried.set()
            return taken

        class Slow(SmallSynthetic):
            @staticmethod
            def generate(spec):
                caller_tried.wait(5)                # still running when its caller tries to take it back
                return synthetic.generate(spec)

        actor = self.make(synthetic_module=Slow)
        with mock.patch.object(engine._Reply, "take", take):
            result = actor.command("open_market", {"seed": 4}, timeout=0.05)
        self.assertTrue(caller_tried.is_set())
        self.assertEqual(result, {"ok": True, "market_id": "1.999000004"})


class ClockAndFrameTests(EngineCase):

    def test_first_frame_is_the_opening_image_paused(self):
        actor = self.make()
        actor.command("open_market", {"seed": 21})
        published = self.frame(actor)
        frame = published.frame
        start_pt = messages(21)[0]["pt"]
        self.assertEqual(frame["t"], "frame")
        self.assertEqual(frame["clock"], {"pt": start_pt, "speed_x100": 100, "paused": True, "pause_reason": "ready",
                                          "ms_to_off": 120_000})
        self.assertEqual(frame["market"]["id"], "1.999000021")
        self.assertEqual(frame["market"]["status"], "OPEN")
        self.assertIs(frame["market"]["inplay"], False)
        self.assertIsNone(frame["market"]["invalid_reason"])
        self.assertEqual([runner["name"] for runner in frame["runners"]], ["Synthetic %d" % n for n in range(1, 6)])
        self.assertEqual(floats_in(frame), 0)
        self.assertEqual(published.line, (__import__("json").dumps(frame, separators=(",", ":")) + "\n").encode())
        self.assert_matches_reference(frame, 21, start_pt)

    def test_a_market_with_no_ladder_definition_renders_as_before(self):
        # DESIGN.md 11.1, "the ladder type is ignored" (Nuance's PR #4 review, item 10): build_frame never reads the
        # ladder type, so a keyless market (synthetic no_ladder_definition; Nuance's PR #1 review, item 1(d)) gives
        # the very frame its CLASSIC twin gives, invalid_reason None included. Its own field is owed before real data.
        class Keyless(SmallSynthetic):
            @staticmethod
            def Spec(seed):
                return synthetic.Spec(seed=seed, runners=5, pre_off_s=120, inplay_s=20,
                                      options={synthetic.NO_LADDER_DEFINITION})

        frames = []
        for module in (SmallSynthetic, Keyless):
            actor = self.make(synthetic_module=module)
            self.assertEqual(actor.command("open_market", {"seed": 21}), {"ok": True, "market_id": "1.999000021"})
            frames.append(self.frame(actor).frame)
        self.assertEqual(frames[1], frames[0])
        self.assertIsNone(frames[1]["market"]["invalid_reason"])

    def assert_matches_reference(self, frame, seed, pt):
        market_id, snapshot = reference(seed, pt)
        self.assertEqual(frame["market"]["id"], market_id)
        self.assertEqual(frame["market"]["status"], snapshot["status"])
        self.assertEqual(frame["market"]["version"], snapshot["version"])
        by_id = {runner["id"]: runner for runner in frame["runners"]}
        self.assertEqual(set(by_id), {int(selection) for selection in snapshot["runners"]})
        for selection, entry in snapshot["runners"].items():
            runner = by_id[int(selection)]
            self.assertEqual(runner["status"], entry["status"])
            self.assertEqual(runner["ltp_h"], None if entry["ltp"] is None else rx.ticks.to_hundredths(entry["ltp"]))
            total = entry["total_matched"]
            self.assertEqual(runner["tv_p"], None if total is None else rx.ticks.to_pence(total) // 2)
            for side in ("back", "lay"):
                expected = [[rx.ticks.to_hundredths(p), rx.ticks.to_pence(s)] for p, s in entry[side][:3]]
                self.assertEqual(runner[side], expected, side)

    def test_play_applies_whole_batches_up_to_the_target(self):
        actor = self.make()
        first = self.open_and_play(actor)
        start = first.frame["clock"]["pt"]
        # Find a pt that several messages share, and move the clock exactly onto it.
        pts = [message["pt"] for message in messages(21)]
        shared = next(pt for pt in pts if pts.count(pt) > 1 and pt - start > 1000)
        self.clock.advance_ms(shared - start)
        published = self.frame(actor, first.seq, lambda frame: frame["clock"]["pt"] == shared)
        self.assertEqual(actor.command("pause", {}), {"ok": True})
        paused = self.frame(actor, published.seq, lambda frame: frame["clock"]["paused"], step_ms=100)
        self.assertEqual(paused.frame["clock"]["pt"], shared)
        self.assertEqual(paused.frame["clock"]["pause_reason"], "user")
        self.assertEqual(paused.frame["clock"]["ms_to_off"], start + 120_000 - shared)
        self.assert_matches_reference(paused.frame, 21, shared)
        market_id, snapshot = reference(21, shared)
        self.assertEqual(actor._market.cache.snapshot(market_id, unreliable_ok=True), snapshot)   # paused: stable

    def test_speed_scales_the_clock(self):
        actor = self.make()
        first = self.open_and_play(actor)
        start = first.frame["clock"]["pt"]
        self.assertEqual(actor.command("set_speed", {"speed_x100": 3000}), {"ok": True})
        self.clock.advance_ms(1000)
        published = self.frame(actor, first.seq, lambda frame: frame["clock"]["pt"] == start + 30_000)
        self.assertEqual(published.frame["clock"]["speed_x100"], 3000)
        self.assertEqual(actor.command("set_speed", {"speed_x100": 25}), {"ok": True})
        self.clock.advance_ms(4000)
        self.frame(actor, published.seq, lambda frame: frame["clock"]["pt"] == start + 31_000)

    def test_frames_are_rate_limited_and_only_on_change(self):
        actor = self.make()
        first = self.open_and_play(actor)
        self.clock.advance_ms(50)                       # under 1/frame_hz since the first frame: no new frame yet
        published, _ = actor.wait(first.seq, 0.3)
        self.assertIsNone(published)
        self.clock.advance_ms(60)
        published = self.frame(actor, first.seq)
        self.assertEqual(published.seq, first.seq + 1)
        self.assertEqual(actor.command("pause", {}), {"ok": True})
        paused = self.frame(actor, published.seq, lambda frame: frame["clock"]["paused"], step_ms=100)
        self.clock.advance_ms(5000)                     # paused and nothing changed: no further frame
        self.assertEqual(actor.wait(paused.seq, 0.3), (None, None))

    def test_the_watcher_leaving_pauses_the_clock(self):
        actor = self.make()
        first = self.open_and_play(actor)
        actor.set_watched(False)
        self.clock.advance_ms(200)
        paused = self.frame(actor, first.seq, lambda frame: frame["clock"]["paused"])
        self.assertEqual(paused.frame["clock"]["pause_reason"], "not_watched")
        self.assertEqual(actor.command("play", {}), {"ok": False, "code": "not_watched"})

    def test_replay_runs_to_closed_with_no_spoiler_before_the_off(self):
        actor = self.make()
        first = self.open_and_play(actor)
        self.assertEqual(actor.command("set_speed", {"speed_x100": 6000}), {"ok": True})
        frames, seq = [first.frame], first.seq
        while True:
            self.clock.advance_ms(500)                  # 30 s of replay per step at 60x
            published = self.frame(actor, seq)
            seq = published.seq
            frames.append(published.frame)
            if published.frame["clock"]["paused"]:
                break
        last = frames[-1]
        self.assertEqual(last["clock"]["pause_reason"], "end_of_market")
        self.assertEqual(last["clock"]["pt"], messages(21)[-1]["pt"])
        self.assertEqual(last["market"]["status"], "CLOSED")
        self.assertEqual(sorted(runner["status"] for runner in last["runners"]).count("WINNER"), 1)
        for frame in frames:
            if frame["clock"]["ms_to_off"] > 0:        # the generator flips at exactly marketTime (DESIGN.md 11.1)
                self.assertFalse(frame["market"]["inplay"])
                self.assertEqual({runner["status"] for runner in frame["runners"]}, {"ACTIVE"})
            self.assertEqual(floats_in(frame), 0)
            text = __import__("json").dumps(frame)
            for word in ("bsp", "winner_id", "WINNER") if frame["market"]["status"] != "CLOSED" else ("bsp",):
                self.assertNotIn(word, text)
        self.assertTrue(any(frame["market"]["inplay"] for frame in frames))
        self.assertEqual(actor.command("play", {}), {"ok": False, "code": "end_of_market"})

    def test_an_unknown_traded_volume_is_null_and_never_carried_across_an_image(self):
        # Nuance's PR #4 review, item 2. The cache resets tv to None on every image (book.py:111, :239-240). Here
        # the opening image comes again 1 s later with no tv: every runner then has tv_p null, never 0 and never
        # the earlier value.
        class Reimaged(SmallSynthetic):
            @staticmethod
            def generate(spec):
                market = synthetic.generate(spec)
                first = next(market.messages())
                again = copy.deepcopy(first)
                again["pt"] += 1000
                for entry in again["mc"][0]["rc"]:
                    entry.pop("tv", None)

                class Wrapped:
                    market_id = market.market_id
                    selection_ids = market.selection_ids
                    runner_names = market.runner_names

                    @staticmethod
                    def messages():
                        return iter([copy.deepcopy(first), copy.deepcopy(again)])
                return Wrapped

        actor = self.make(synthetic_module=Reimaged)
        first = self.open_and_play(actor)
        before = [runner["tv_p"] for runner in first.frame["runners"]]
        self.assertTrue(any(type(value) is int and value > 0 for value in before), before)
        self.clock.advance_ms(1000)
        pt = first.frame["clock"]["pt"] + 1000
        after = self.frame(actor, first.seq, lambda frame: frame["clock"]["pt"] == pt)
        self.assertEqual([runner["tv_p"] for runner in after.frame["runners"]], [None] * len(before))

    def test_a_market_time_out_of_range_stops_the_replay_not_the_engine(self):
        # Nuance's PR #4 review, item 9. replay_market_time catches only ValueError (book.py:68-79), so this
        # marketTime raised OverflowError and ended the engine with engine_failed. Now the replay stops at that
        # message with value_error, and the engine stays up. Spec takes only Z times: only a crafted stream has one.
        class Overflowing(SmallSynthetic):
            @staticmethod
            def generate(spec):
                market = synthetic.generate(spec)
                stream = list(market.messages())
                bad = {"op": "mcm", "clk": stream[1]["clk"], "pt": stream[0]["pt"] + 1000, "mc": [{
                    "id": market.market_id, "marketDefinition": dict(stream[0]["mc"][0]["marketDefinition"],
                                                                     marketTime="0001-01-01T00:00:00.000+23:59")}]}
                later = dict(copy.deepcopy(stream[1]), pt=stream[0]["pt"] + 2000)

                class Wrapped:
                    market_id = market.market_id
                    selection_ids = market.selection_ids
                    runner_names = market.runner_names

                    @staticmethod
                    def messages():
                        return iter([copy.deepcopy(stream[0]), copy.deepcopy(bad), copy.deepcopy(later)])
                return Wrapped

        actor = self.make(synthetic_module=Overflowing)
        first = self.open_and_play(actor)
        self.clock.advance_ms(2000)
        stopped = self.frame(actor, first.seq, lambda frame: frame["clock"]["paused"], step_ms=100)
        self.assertEqual((stopped.frame["clock"]["pause_reason"], stopped.frame["clock"]["pt"]),
                         ("end_of_market", first.frame["clock"]["pt"] + 1000))
        self.assertEqual((stopped.frame["market"]["invalid_reason"], stopped.frame["runners"]), ("value_error", []))
        self.assertEqual(actor.command("play", {}), {"ok": False, "code": "end_of_market"})
        self.assertIsNone(actor.ended())

    def test_opening_another_market_replaces_the_first(self):
        actor = self.make()
        first = self.open_and_play(actor)
        self.clock.advance_ms(2000)
        self.assertEqual(actor.command("open_market", {"seed": 22}), {"ok": True, "market_id": "1.999000022"})
        published = self.frame(actor, first.seq, lambda frame: frame["market"]["id"] == "1.999000022")
        self.assertEqual(published.frame["clock"]["pause_reason"], "ready")
        self.assertEqual(published.frame["clock"]["pt"], messages(22)[0]["pt"])


class RunMarkerTests(EngineCase):
    """I-17 on the actor: the marker freezes the clock at once, refuses commands and ends after the grace."""

    def test_marker_freezes_then_ends(self):
        actor = self.make(grace_s=0.5)
        first = self.open_and_play(actor)
        self.clock.advance_ms(1000)
        moving = self.frame(actor, first.seq, lambda frame: frame["clock"]["pt"] > first.frame["clock"]["pt"])
        os.makedirs(os.path.dirname(self.marker))
        open(self.marker, "w").close()
        self.clock.advance_ms(5000)                     # the frozen clock must not move with wall time
        frozen = self.frame(actor, moving.seq, lambda frame: frame["clock"]["pause_reason"] == "run_marker")
        self.assertTrue(frozen.frame["clock"]["paused"])
        self.assertEqual(frozen.frame["clock"]["pt"], moving.frame["clock"]["pt"])
        self.assertEqual(actor.command("play", {}), {"ok": False, "code": "run_marker_present"})
        self.assertEqual(actor.command("open_market", {"seed": 1}), {"ok": False, "code": "run_marker_present"})
        self.clock.advance_ms(600)                      # past the grace period
        self.assertTrue(actor.stopped.wait(5))
        self.assertEqual(actor.ended(), "run_marker")
        self.assertEqual(actor.wait(frozen.seq, 0.1), (None, "run_marker"))

    def test_a_marker_that_goes_away_still_ends_the_engine(self):
        actor = self.make(grace_s=0.5)
        first = self.open_and_play(actor)
        os.makedirs(os.path.dirname(self.marker))
        open(self.marker, "w").close()
        self.clock.advance_ms(150)
        self.frame(actor, first.seq, lambda frame: frame["clock"]["pause_reason"] == "run_marker")
        os.remove(self.marker)
        self.assertEqual(actor.command("play", {}), {"ok": False, "code": "run_marker_present"})
        self.clock.advance_ms(600)
        self.assertTrue(actor.stopped.wait(5))
        self.assertEqual(actor.ended(), "run_marker")

    def test_a_command_dequeued_after_the_marker_appeared_is_refused(self):
        actor = self.make(tick_s=3600)              # no timed wake: only the command itself can meet the marker
        self.assertEqual(actor.command("open_market", {"seed": 1}), {"ok": True, "market_id": "1.999000001"})
        first = self.frame(actor)                   # published after that loop's own marker check
        os.makedirs(os.path.dirname(self.marker))
        open(self.marker, "w").close()
        self.assertEqual(actor.command("open_market", {"seed": 2}), {"ok": False, "code": "run_marker_present"})
        frozen = self.frame(actor, first.seq, step_ms=100)
        self.assertEqual(frozen.frame["clock"]["pause_reason"], "run_marker")
        self.assertEqual(frozen.frame["market"]["id"], "1.999000001")

    def test_unreadable_marker_directory_counts_as_present(self):
        actor = self.make(grace_s=0.2)
        first = self.open_and_play(actor)
        directory = os.path.dirname(self.marker)
        os.makedirs(directory)
        os.chmod(directory, 0)
        self.addCleanup(os.chmod, directory, 0o700)
        self.clock.advance_ms(150)
        self.frame(actor, first.seq, lambda frame: frame["clock"]["pause_reason"] == "run_marker")
        self.clock.advance_ms(300)
        self.assertTrue(actor.stopped.wait(5))
        self.assertEqual(actor.ended(), "run_marker")


class ConversionTests(unittest.TestCase):

    def test_prices_and_money_become_integers(self):
        self.assertEqual(engine.price_h(2.5), 250)
        self.assertEqual(engine.price_h(1000), 100000)
        for value in (1.0, 0.5, None, True, float("nan"), float("inf"), 3.456, "NaN"):
            self.assertIsNone(engine.price_h(value), value)
        self.assertEqual(engine.pence(12.34), 1234)
        self.assertEqual(engine.pence(7), 700)
        self.assertEqual(engine.pence(1.005), 100)          # more than 2 dp: floored, never a float
        for value in (None, True, float("nan"), float("inf")):
            self.assertIsNone(engine.pence(value), value)
        self.assertEqual(engine.ladder([[4.6, 139.63], [4.4, 1e-9], [4.3, None], [4.2, 2.0], [4.1, 3.0], [4.0, 4.0]]),
                         [[460, 13963], [420, 200], [410, 300]])

    def test_off_ladder_prices(self):
        # The LTP keeps a price that is off the tick ladder, within 1.01 to 1000 (whether a real LTP can be off it,
        # after a BSP-matched trade say, is unverified); a ladder level off the CLASSIC ladder is dropped.
        self.assertEqual(engine.price_h(2.03), 203)
        self.assertEqual(engine.price_h(4.15), 415)
        self.assertEqual(engine.price_h(1.01), 101)
        for value in (1010, 1000.5, 1000.01, 1.005):
            self.assertIsNone(engine.price_h(value), value)
        self.assertEqual(engine.ladder([[2.03, 5.0], [2.02, 6.0], [1.99, 7.0]]), [[202, 600], [199, 700]])
        self.assertEqual(engine.ladder([[2.05, 5.0], [2.04, 6.0], [2.03, 1.0], [2.01, 1.0], [2.0, 8.0], [1.99, 9.0]]),
                         [[204, 600], [200, 800], [199, 900]])
        self.assertEqual(engine.ladder([[1010, 5.0], [1000.5, 5.0], [21.5, 5.0], [1000, 1.0]]), [[100000, 100]])


if __name__ == "__main__":
    unittest.main()
