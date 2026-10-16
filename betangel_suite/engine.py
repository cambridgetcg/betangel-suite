"""The Phase 0b engine: one synthetic market replayed on an actor thread (DESIGN.md 3.2, 6.1, 6.5, 6.8).

One actor thread owns every piece of mutable replay state: the market's messages, the
book.MarketBookCache (through rx), the sim clock and the latest frame. Other threads only enqueue
commands (command(), pause_external(), set_watched(), stop()) and read published frames, which the actor
publishes by swapping a reference under a condition variable (wait()). So no replay state needs a lock.

Phase 0b is synthetic only. The engine refuses to start when the config names any data root
(synthetic_only), and open_market accepts nothing but a seed: the market comes from
betangel_suite.synthetic.generate, and every market id it carries must be in the reserved namespace
(not_synthetic). Nothing here reads or writes a file, except the run-marker check.

The clock (section 6.1) runs on the publisher-time axis (pt, integer ms). While playing,
target = V0 + (wall_now - wall_anchor) * speed_x100 / 100, in integer nanoseconds; every whole pt batch
with pt <= target is applied, never part of one. Wall time is time.monotonic_ns and paces only. The clock
runs only while the controller tab is watching (set_watched; section 8.6): play is refused otherwise,
and losing the watcher pauses with reason not_watched. The replay stops at the last message.

Frames (section 6.5, the Phase 0b subset) are built at most frame_hz times a second and only when
something changed. Every number in a frame is an integer: prices in hundredths and sizes in pence through
rx.ticks, traded volume in pence on the repo's PRO basis (divided by 2, paper.py:1016).

The run marker (section 6.8, I-17) is checked on every tick and again before each command runs. When it
appears, the engine freezes: the clock pauses with reason run_marker, no message is applied, every command is
refused with run_marker_present, and after the grace period the engine ends with reason run_marker. Nothing
is written.

A command that waits longer than its timeout to start is taken back and answered engine_busy: it has not run
and never will (_Reply). One the actor has started always gets its real result.
Standard library only, plus rx.
"""

import collections
import json
import queue
import sys
import threading
import time
from decimal import ROUND_FLOOR, Decimal

from . import errors, runmarker
from .errors import SuiteError

SPEEDS_X100 = (25, 50, 100, 200, 500, 1000, 3000, 6000)    # 0.25x .. 60x (section 6.1)
DEFAULT_SPEED_X100 = 100
TICK_S = 0.025                      # the actor wakes at least every 25 ms (section 3.2: 20-50 ms)
MARKER_GRACE_S = 30                 # section 6.8
LADDER_DEPTH = 3                    # best 3 back and lay in the Phase 0b frame
TV_DIVISOR = 2                      # PRO historical basis (paper.py traded_volume_divisor)
COMMAND_TIMEOUT_S = 5.0
SEED_MAX = 2 ** 31 - 1
PAUSE_REASONS = ("ready", "user", "stop", "not_watched", "run_marker", "end_of_market", "takeover", "control")
END_REASONS = ("stopped", "run_marker", "engine_failed", "abandoned", "max_session")    # the last two: api/lifetime.py
COMMANDS = ("open_market", "play", "pause", "set_speed", "stop")     # what the actor implements in Phase 0b
_NS_PER_MS_X100 = 100_000_000       # ns per ms, times the 100 of speed_x100

Published = collections.namedtuple("Published", "seq frame line")


class _Reply:
    """A queued command's reply. The actor and a caller whose wait timed out each try take(); only the first
    succeeds. The actor runs only a command it took, and a caller answers engine_busy only for one it took
    back, so a command answered engine_busy has not run and never will."""

    __slots__ = ("event", "value", "_taken")

    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self._taken = threading.Lock()

    def take(self):
        """True for the first caller only (an atomic test-and-set)."""
        return self._taken.acquire(blocking=False)

    def set(self, value):
        self.value = value
        self.event.set()


def _ok(**fields):
    return dict(ok=True, **fields)


def _refused(code):
    return {"ok": False, "code": SuiteError(code).code}


class _Market:
    """The open market: its message batches, the cache, the clock and the display tap (actor only)."""

    def __init__(self, market_id, batches, cache, names):
        self.market_id = market_id
        self.batches = batches              # [(pt, (msg, ...)), ...] in pt order
        self.cache = cache
        self.market_time_ms = None          # the published marketTime at V (from the definition), in ms
        self.names = names                  # selection id (int) -> name from the generator
        self.next = 0                       # index of the next batch to apply
        self.v = batches[0][0]              # the virtual time, pt ms
        self.definition = None              # the latest marketDefinition for this market (names, order)
        self.error = None                   # code of an apply failure; the replay stops there
        self.anchor_v = self.v
        self.anchor_ns = 0


class Engine:
    """The actor. Construct, start(), then talk to it only through the public methods."""

    def __init__(self, cfg, *, marker_path, synthetic=None, clock_ns=time.monotonic_ns, tick_s=TICK_S,
                 marker_grace_s=MARKER_GRACE_S):
        if cfg.get("data_roots"):
            raise SuiteError("synthetic_only")          # Phase 0b refuses every configured data root
        frame_hz = cfg.get("frame_hz")
        if type(frame_hz) is not int or not 5 <= frame_hz <= 20:
            raise SuiteError("config_invalid_value")
        self.frame_hz = frame_hz
        self._min_frame_ns = 1_000_000_000 // frame_hz
        self._marker_path = marker_path
        self._synthetic = synthetic
        self._clock_ns = clock_ns
        self._tick_s = tick_s
        self._grace_ns = int(marker_grace_s * 1_000_000_000)
        self._queue = queue.Queue()
        self._cond = threading.Condition()
        self._published = None
        self._ended = None
        self._thread = None
        self.stopped = threading.Event()
        # actor-only state
        self._market = None
        self._speed = DEFAULT_SPEED_X100
        self._paused = True
        self._pause_reason = None
        self._watched = False
        self._frozen_at = None
        self._dirty = False
        self._last_publish_ns = None
        self._seq = 0

    # --- the public, thread-safe side ---------------------------------------------------------------

    def start(self):
        if self._thread is not None:
            raise SuiteError("engine_failed")
        self._thread = threading.Thread(target=self._run, name="suite-actor", daemon=True)
        self._thread.start()

    def command(self, name, args, timeout=COMMAND_TIMEOUT_S):
        """Run one Phase 0b command (COMMANDS) on the actor; returns {"ok": True, ...} or {"ok": False, "code": ...}."""
        if name not in COMMANDS:
            return _refused("not_implemented")
        return self._call(name, args, timeout)

    def pause_external(self, reason, timeout=COMMAND_TIMEOUT_S):
        """Pause from outside the API (control socket pause or a takeover)."""
        return self._call("_pause", reason, timeout)

    def set_watched(self, watched):
        """Tell the actor whether the controller tab's stream is connected (section 8.6)."""
        self._queue.put(("_watched", bool(watched), None))

    def stop(self, reason="stopped"):
        """Ask the actor to end; streams then get an end line with this reason."""
        self._queue.put(("_stop", reason, None))

    def started(self):
        return self._thread is not None

    def ended(self):
        """The end reason once the actor has stopped, else None."""
        return self._ended

    def latest(self):
        return self._published

    def wait(self, after_seq, timeout):
        """(Published or None, end reason or None): the latest frame once its seq is above after_seq, else the
        end reason once the engine has ended, else (None, None) after timeout seconds."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                published = self._published
                if published is not None and published.seq > after_seq:
                    return published, self._ended
                if self._ended is not None:
                    return None, self._ended
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, None
                self._cond.wait(remaining)

    def join(self, timeout):
        if self._thread is not None:
            self._thread.join(timeout)

    def _call(self, name, args, timeout):
        if self._ended is not None:
            return _refused("engine_stopping")
        reply = _Reply()
        self._queue.put((name, args, reply))
        if not reply.event.wait(timeout) and reply.take():     # taken back before the actor took it
            return _refused("engine_stopping" if self._ended is not None else "engine_busy")
        reply.event.wait()              # the actor took it, and answers every command it takes
        return reply.value

    # --- the actor ----------------------------------------------------------------------------------

    def _run(self):
        reason = "engine_failed"
        try:
            reason = self._loop()
        finally:
            with self._cond:
                self._ended = reason if reason in END_REASONS else "engine_failed"
                self._cond.notify_all()
            self._drain()
            self.stopped.set()

    def _loop(self):
        while True:
            now = self._clock_ns()
            if self._frozen_at is None and runmarker.active(self._marker_path):
                self._freeze(now)
            if self._frozen_at is None:
                self._advance(now)
            elif now - self._frozen_at >= self._grace_ns:
                return "run_marker"             # frozen engines always end, even if the marker went away
            self._maybe_publish(now)
            try:
                name, args, reply = self._queue.get(timeout=self._wait_s(now))
            except queue.Empty:
                continue
            if name == "_stop":
                return args if args in END_REASONS else "stopped"
            if self._frozen_at is None and name != "_watched" and runmarker.active(self._marker_path):
                self._freeze(self._clock_ns())      # appeared since this tick's check: _handle refuses the command
            if reply is not None and not reply.take():
                continue                        # its caller timed out and took it back: it never runs
            result = _refused("internal_error")
            try:
                result = self._handle(name, args)
            except SuiteError as exc:
                result = _refused(exc.code)
            except Exception as exc:        # a failing command must not take the actor down; code only
                sys.stderr.write("engine:" + errors.describe(exc) + "\n")
                result = _refused("internal_error")
            finally:
                if reply is not None:
                    reply.set(result)           # its caller waits for this once the actor has taken it

    def _wait_s(self, now):
        """Sleep until the next tick, or sooner when a waiting frame becomes due (frames then come at frame_hz)."""
        if self._dirty and self._market is not None and self._last_publish_ns is not None:
            due_ns = self._last_publish_ns + self._min_frame_ns - now
            if 0 < due_ns < self._tick_s * 1_000_000_000:
                return due_ns / 1_000_000_000
        return self._tick_s

    def _drain(self):
        """Answer every command still queued after the actor stopped."""
        while True:
            try:
                _name, _args, reply = self._queue.get_nowait()
            except queue.Empty:
                return
            if reply is not None:
                reply.set(_refused("engine_stopping"))

    def _freeze(self, now):
        """The marker appeared: pause at once, applying nothing more, and refuse everything (section 6.8)."""
        self._frozen_at = now
        self._paused, self._pause_reason = True, "run_marker"
        self._dirty = True

    def _handle(self, name, args):
        if name == "_watched":
            self._watched = args
            if not args and not self._paused:
                self._set_paused("not_watched")
            return None
        if self._frozen_at is not None:
            return _refused("run_marker_present")
        if name == "_pause":
            if self._market is not None:
                self._set_paused(args if args in PAUSE_REASONS else "control")
            return _ok()
        handler = getattr(self, "_do_" + name, None)
        if name not in COMMANDS or handler is None:
            return _refused("not_implemented")
        return handler(args)

    def _do_open_market(self, args):
        seed = args.get("seed") if isinstance(args, dict) else None
        if type(seed) is not int or not 0 <= seed <= SEED_MAX:
            return _refused("bad_args")
        synthetic = self._synthetic_module()
        market = synthetic.generate(synthetic.Spec(seed=seed))      # deterministic for equal specs
        market_id = market.market_id
        if not synthetic.is_synthetic_market_id(market_id):
            return _refused("not_synthetic")
        batches = []
        for message in market.messages():
            if not isinstance(message, dict) or type(message.get("pt")) is not int:
                return _refused("bad_args")
            for change in message.get("mc") or ():
                if not isinstance(change, dict) or not synthetic.is_synthetic_market_id(change.get("id")):
                    return _refused("not_synthetic")
            if batches and batches[-1][0] == message["pt"]:
                batches[-1][1].append(message)
            else:
                batches.append((message["pt"], [message]))
        if not batches:
            return _refused("no_market")
        from . import rx            # here, not at the top: rx needs the armed guard and the verified pin
        cache = rx.book.MarketBookCache(key_type="historical", app_key_slot=None, source="recording")
        names = {}
        for selection_id, name in zip(market.selection_ids, market.runner_names):
            names[selection_id] = name
        self._paused, self._pause_reason = True, "ready"     # before the switch: never advance the new market
        self._market = _Market(market_id, [(pt, tuple(group)) for pt, group in batches], cache, names)
        self._apply_batch(self._market)          # the definition image at T-pre_off: a valid first frame
        return _ok(market_id=market_id)

    def _do_play(self, args):
        market = self._market
        if market is None:
            return _refused("no_market")
        if market.error is not None or market.next >= len(market.batches):
            return _refused("end_of_market")
        if not self._watched:
            return _refused("not_watched")
        if self._paused:
            self._paused, self._pause_reason = False, None
            self._anchor(self._clock_ns())
            self._dirty = True
        return _ok()

    def _do_pause(self, args):
        if self._market is None:
            return _refused("no_market")
        if not self._paused:
            self._set_paused("user")
        return _ok()

    def _do_set_speed(self, args):
        speed = args.get("speed_x100") if isinstance(args, dict) else None
        if type(speed) is not int or speed not in SPEEDS_X100:
            return _refused("bad_args")
        now = self._clock_ns()
        if self._market is not None and not self._paused:
            self._advance(now)              # bring V up to now at the old speed, then re-anchor
            self._anchor(now)
        self._speed = speed
        self._dirty = True
        return _ok()

    def _do_stop(self, args):
        """STOP (paper) in Phase 0b: pause with reason stop. Paper orders arrive in Phase 1b (section 7.6)."""
        if self._market is not None:
            self._set_paused("stop")
        return _ok()

    def _synthetic_module(self):
        if self._synthetic is None:
            from . import synthetic             # here, not at the top: engine code reaches upstream only through rx
            self._synthetic = synthetic
        return self._synthetic

    # --- the clock ----------------------------------------------------------------------------------

    def _anchor(self, now):
        market = self._market
        market.anchor_v, market.anchor_ns = market.v, now

    def _set_paused(self, reason):
        if self._market is not None and not self._paused:
            self._advance(self._clock_ns())
        self._paused, self._pause_reason = True, reason
        self._dirty = True

    def _advance(self, now):
        market = self._market
        if market is None or self._paused:
            return
        target = market.anchor_v + (now - market.anchor_ns) * self._speed // _NS_PER_MS_X100
        while market.next < len(market.batches) and market.batches[market.next][0] <= target:
            self._apply_batch(market)               # marks the frame dirty
            if market.error is not None:
                break
        if market.error is not None or market.next >= len(market.batches):
            market.v = market.batches[market.next - 1][0]
            self._paused, self._pause_reason = True, "end_of_market"
            self._dirty = True
        elif target != market.v:
            market.v = target
            self._dirty = True

    def _apply_batch(self, market):
        from . import rx
        pt, messages = market.batches[market.next]
        for message in messages:
            try:
                rx.call(market.cache.apply, message)
            except SuiteError as exc:
                market.error = exc.code
                break
            for change in message.get("mc") or ():
                if change.get("id") == market.market_id and isinstance(change.get("marketDefinition"), dict):
                    market.definition = change["marketDefinition"]        # replaced whole, as book.py does
                    market.market_time_ms = market_time_ms(market.definition)
        market.next += 1
        market.v = max(market.v, pt)
        self._dirty = True

    # --- frames -------------------------------------------------------------------------------------

    def _maybe_publish(self, now):
        if not self._dirty or self._market is None:
            return
        if self._last_publish_ns is not None and now - self._last_publish_ns < self._min_frame_ns:
            return
        self._seq += 1
        frame = build_frame(self._seq, self._clock_fields(), self._market, self._snapshot())
        line = json.dumps(frame, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"
        with self._cond:
            self._published = Published(self._seq, frame, line)
            self._cond.notify_all()
        self._dirty = False
        self._last_publish_ns = now

    def _clock_fields(self):
        market = self._market
        ms_to_off = None if market.market_time_ms is None else market.market_time_ms - market.v
        return {"pt": market.v, "speed_x100": self._speed, "paused": self._paused,
                "pause_reason": self._pause_reason, "ms_to_off": ms_to_off}

    def _snapshot(self):
        """(snapshot, None) or (None, code) for the open market at the current position."""
        from . import rx
        market = self._market
        if market.error is not None:
            return None, market.error
        try:
            return rx.call(market.cache.snapshot, market.market_id, unreliable_ok=True), None
        except SuiteError as exc:
            return None, exc.reason or exc.code


# --- frame building (pure) ----------------------------------------------------------------------------

def market_time_ms(definition):
    """The definition's published marketTime in whole ms (book.replay_market_time's shape), else None."""
    from . import rx
    text = rx.book.replay_market_time(definition.get("marketTime"))
    if text is None:
        return None
    try:
        return rx.receipts.parse_utc_ns(text) // 1_000_000
    except ValueError:
        return None


def price_h(value):
    """An int price in hundredths inside the CLASSIC ladder's range (1.01 to 1000), or None for a missing,
    non-finite, out-of-range or more-than-2-dp price. It need not be a tick of the ladder: the LTP keeps such a
    price as it is, because a BSP-matched trade can be off the ladder. ladder() drops off-ladder levels."""
    from . import rx
    if value is None or isinstance(value, bool):
        return None
    try:
        result = rx.ticks.to_hundredths(value)
    except ValueError:
        return None
    return result if rx.ticks.LADDER_CLASSIC[0] <= result <= rx.ticks.LADDER_CLASSIC[-1] else None


def pence(value):
    """An int amount in pence (rx.ticks.to_pence), floored when the value has more than 2 dp; None if missing."""
    from . import rx
    if value is None or isinstance(value, bool):
        return None
    try:
        return rx.ticks.to_pence(value)
    except ValueError:
        pass
    try:
        exact = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
        if not exact.is_finite():
            return None
        return int((exact * 100).to_integral_value(rounding=ROUND_FLOOR))
    except (ArithmeticError, ValueError, TypeError):
        return None


def ladder(levels):
    """[[price_h, size_p], ...]: the first LADDER_DEPTH convertible levels, best first as the snapshot has them.
    A level whose price is not a tick of the CLASSIC ladder (rx.ticks.is_on_ladder) is dropped."""
    from . import rx
    out = []
    for level in levels or ():
        if len(out) == LADDER_DEPTH:
            break
        if not isinstance(level, (list, tuple)) or len(level) != 2:
            continue
        price, size = price_h(level[0]), pence(level[1])
        if price is not None and rx.ticks.is_on_ladder(price) and size is not None and size > 0:
            out.append([price, size])
    return out


def _text(value, default=""):
    return value if isinstance(value, str) else default


def market_name(definition, market_id):
    """A display name from the definition (venue and race name), else the market id."""
    if isinstance(definition, dict):
        parts = [_text(definition.get(key)) for key in ("venue", "name")]
        name = " ".join(part for part in parts if part)
        if name:
            return name
        if _text(definition.get("eventName")):
            return definition["eventName"]
    return market_id


def _runner_order(definition):
    """selection id (str) -> (sortPriority or position, position) from the definition's runners."""
    order = {}
    runners = definition.get("runners") if isinstance(definition, dict) else None
    for position, runner in enumerate(runners if isinstance(runners, list) else ()):
        if isinstance(runner, dict) and type(runner.get("id")) is int:
            priority = runner.get("sortPriority")
            order[str(runner["id"])] = (priority if type(priority) is int else position, position,
                                        _text(runner.get("name")))
    return order


def build_frame(seq, clock, market, snapshot_and_error):
    """The Phase 0b frame (section 6.5 subset; the shared interface (2)). Integers only."""
    snapshot, error = snapshot_and_error
    definition = market.definition
    order = _runner_order(definition)
    if snapshot is None:
        status = _text(definition.get("status"), "INACTIVE") if isinstance(definition, dict) else "INACTIVE"
        in_play = definition.get("inPlay") is True if isinstance(definition, dict) else False
        version = definition.get("version") if isinstance(definition, dict) else None
        invalid = error or "market_definition_missing"
        runners = []
    else:
        status, in_play, version = snapshot["status"], snapshot["inplay"], snapshot["version"]
        invalid = snapshot["invalid_reason"]
        runners = []
        for selection, entry in snapshot["runners"].items():
            selection_id = int(selection)
            rank = order.get(selection, (len(order), len(order), ""))
            name = rank[2] or market.names.get(selection_id, "")
            total = pence(entry.get("total_matched"))
            runners.append((rank[:2], {
                "id": selection_id, "name": name, "status": _text(entry.get("status"), "UNKNOWN"),
                "ltp_h": price_h(entry.get("ltp")), "tv_p": 0 if total is None else total // TV_DIVISOR,
                "back": ladder(entry.get("back")), "lay": ladder(entry.get("lay")),
            }))
        runners = [runner for _rank, runner in sorted(runners, key=lambda item: item[0])]
    return {
        "t": "frame", "seq": seq, "clock": dict(clock),
        "market": {"id": market.market_id, "name": market_name(definition, market.market_id), "status": status,
                   "inplay": bool(in_play), "version": version if type(version) is int else 0,
                   "invalid_reason": invalid},
        "runners": runners,
    }
