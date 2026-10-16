"""Synthetic Betfair PRO historical markets in the reserved namespace (DESIGN.md 5.6 and 11, docs/data-handling.md).

generate(Spec(seed=...)) returns a Market. Its lines() are one PRO historical stream: one JSON "mcm" message per
line, as in the decompressed bytes of a member, with no newline; messages() yields the same lines parsed. Equal
specs give equal bytes on every supported interpreter (random.Random seeded with text, integer pence and ladder
indices inside, floats only at the JSON edge).

Reserved namespace, and nothing else: market ids "1.999" plus six digits, event ids "99" plus six digits, selection
ids 9 plus seven digits, the venue "Synthetic Park" and runners "Synthetic 1".."Synthetic n" (sortPriority order).
The market and event ids come from the seed alone (seed modulo 10**6), so seeds that differ by a multiple of 10**6
share them; give the markets of one archive distinct seeds below that.

What a market holds (times are pt, integer ms; T is the scheduled off, the published marketTime):

- T - pre_off_s: a definition image (img true, status OPEN, inPlay false, bspMarket true) with every runner's full
  available-to-back and available-to-lay ladders (atb/atl), the traded ladder (trd), ltp and tv when the market has
  traded already, and the SP fields (spn, spf, spb, spl) inside the SP window.
- Before the off: deltas at about the real rates of DESIGN.md 6.7: 0.12 messages a second beyond T-2h, rising to
  about 5,000 in the last 10 minutes (real: 3,309-5,922), short bursts of up to about 25 in one second, and a few
  messages sharing a pt; a 26-53 h market has 25,000-40,000 messages, 55-75% of them before T-30m. Prices sit on
  the CLASSIC tick ladder (rx.ticks), drawn with a favourite-longshot bias (market chances proportional to
  true_p ** alpha, alpha < 1); full-depth ladders of near levels plus far offers down to 1.01 and up to 1000 (about
  500-750 book entries at 5 runners and 5,000-5,500 at 44; real: 721-6,166); trades take the best price and move
  ltp, trd and tv (tv is always the sum of trd); spreads tighten and sizes grow towards the off. Every definition
  carries priceLadderDefinition {"type": "CLASSIC"} (validate's V9 refuses any other ladder type).
- trd and tv are on the PRO historical basis, backer's stake x 2 (upstream docs/betfair-facts.md F60), which
  upstream paper (traded_volume_divisor 2) and the engine (engine.TV_DIVISOR) read: a trade that takes s pence
  off atb or atl adds 2 * s to trd at that price and to tv. That atb and atl sizes are backer's stakes is
  unverified.
- T: the in-play flip (one definition: OPEN, inPlay true, betDelay 1, bspReconciled true, every runner's bsp); all
  unmatched offers lapse and thin in-play ladders replace them. The flip always comes at exactly the published
  marketTime, which is never revised, with no SUSPENDED at the off. That shape is this generator's choice: the real
  flip shape is unverified (DESIGN.md 11.1, owed before Phase 1a).
- In play for inplay_s: faster, wider markets converging on the winner.
- T + inplay_s: SUSPENDED; then CLOSED, with WINNER, LOSER (and REMOVED) statuses and settledTime, in the final
  definition.

Every message is accepted by rx.book.MarketBookCache(key_type="historical", app_key_slot=None, source="recording"),
and with no option every snapshot before the off is valid (invalid_reason None).

Options (Spec.options, a frozenset of strings; anything else is refused):

  suspension      the market is SUSPENDED for a few seconds pre-off, then reopened by a fresh image;
  removal         a runner (never the favourite or the winner) is REMOVED pre-off: a SUSPENDED definition with its
                  removalDate and adjustmentFactor, then an image reopening the market with the rest repriced.
                  Every adjustmentFactor is a market chance in percent: the removed runner's is its chance at
                  removal, and the rest are renormalised without it. Betfair's real semantics are unverified;
  nonfinite_sp    pre-off, one runner's spn and spf become the quoted strings "NaN" and "Infinity" and its spl
                  carries a size "Infinity" at 1000 (snapshots in that window are invalid: non_finite_size), until a
                  later message deletes that point and restores the projections;
  no_market_time  the definitions carry no marketTime, suspendTime or openDate;
  month:YYYY-MM   replaces the year and month of Spec.market_time (gate tests).

Market.winner_id, removed_ids and plan are test oracles: an engine must never put them in a frame, and it takes
the time to the off from the stream's marketTime (rx.book.replay_market_time), never from market_time_ms, which
real members do not have.

Engine code: upstream is reached only through rx (ticks, receipts, book), standard library otherwise.
"""

import dataclasses
import datetime
import json
import math
import random
import re

from . import rx

VENUE = "Synthetic Park"
RUNNER_PREFIX = "Synthetic "
MARKET_ID_PREFIX = "1.999"
EVENT_ID_PREFIX = "99"
SELECTION_ID_MIN = 90_000_000
SELECTION_ID_MAX = 99_999_999
EVENT_TYPE_ID = "7"                     # horse racing
OPTIONS = frozenset({"suspension", "removal", "nonfinite_sp", "no_market_time"})
MONTH_OPTION = "month:"
MIN_RUNNERS, MAX_RUNNERS = 2, 60
MIN_PRE_OFF_S, MAX_PRE_OFF_S = 30, 3 * 86_400
MIN_INPLAY_S, MAX_INPLAY_S = 10, 3_600
TV_CAP_P = 300_000_000                  # per runner (GBP 3M): keeps every volume below eight integer digits
GENERATOR_VERSION = 1

_MARKET_ID_RE = re.compile(r"1\.999[0-9]{6}")
_EVENT_ID_RE = re.compile(r"99[0-9]{6}")
_MARKET_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
_MONTH_RE = re.compile(r"month:([0-9]{4}-(?:0[1-9]|1[0-2]))")
_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DISTANCES = ("5f", "6f", "7f", "1m", "1m2f", "1m4f", "2m", "2m4f", "3m")
_RACE_KINDS = ("Hcap", "Mdn Stks", "Nov Stks", "Class Stks", "Hcap Hrd", "Nov Chs")
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

_LADDER = rx.ticks.LADDER_CLASSIC
_TOP = len(_LADDER) - 1
_SP_LAY_PRICE = _TOP                    # 1000: the price nonfinite_sp uses; regular spl stays below it


def is_synthetic_market_id(value):
    """True for a market id in the reserved namespace: "1.999" plus six digits."""
    return isinstance(value, str) and bool(_MARKET_ID_RE.fullmatch(value))


def is_synthetic_event_id(value):
    """True for an event id in the reserved namespace: "99" plus six digits (text, as the stream sends it)."""
    return isinstance(value, str) and bool(_EVENT_ID_RE.fullmatch(value))


def is_synthetic_selection_id(value):
    """True for a selection id in the reserved namespace: 9 plus seven digits."""
    return type(value) is int and SELECTION_ID_MIN <= value <= SELECTION_ID_MAX


def _invalid(name):
    return ValueError("synthetic_spec_invalid:" + name)


def _check_int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise _invalid(name)


@dataclasses.dataclass(frozen=True)
class Spec:
    """What to generate. options may be any iterable of strings; it is stored as a frozenset."""

    seed: int
    runners: int = 8
    pre_off_s: int = 600
    inplay_s: int = 90
    market_time: str = "2015-06-01T14:00:00.000Z"
    options: frozenset = frozenset()

    def __post_init__(self):
        _check_int(self.seed, "seed", 0, (1 << 63) - 1)
        _check_int(self.runners, "runners", MIN_RUNNERS, MAX_RUNNERS)
        _check_int(self.pre_off_s, "pre_off_s", MIN_PRE_OFF_S, MAX_PRE_OFF_S)
        _check_int(self.inplay_s, "inplay_s", MIN_INPLAY_S, MAX_INPLAY_S)
        if isinstance(self.options, (str, bytes)):
            raise _invalid("options")
        try:
            options = frozenset(self.options)
        except TypeError:
            raise _invalid("options") from None
        months = [option for option in options if isinstance(option, str) and option.startswith(MONTH_OPTION)]
        if (any(not isinstance(option, str) for option in options) or len(months) > 1
                or any(not _MONTH_RE.fullmatch(option) for option in months)
                or not options - set(months) <= OPTIONS):
            raise _invalid("options")
        if "removal" in options and self.runners < 3:
            raise _invalid("runners")
        object.__setattr__(self, "options", options)
        if not isinstance(self.market_time, str) or not _MARKET_TIME_RE.fullmatch(self.market_time):
            raise _invalid("market_time")
        if _time_ms(self.effective_market_time()) - self.pre_off_s * 1000 < 0:   # also: the month gives a real date
            raise _invalid("market_time")

    def month_override(self):
        """The YYYY-MM of a month:YYYY-MM option, or None."""
        for option in self.options:
            if option.startswith(MONTH_OPTION):
                return option[len(MONTH_OPTION):]
        return None

    def effective_market_time(self):
        """market_time with the month option applied (what the market is scheduled for)."""
        month = self.month_override()
        return self.market_time if month is None else month + self.market_time[7:]


def _time_ms(text):
    """Whole UTC milliseconds of a marketTime-shaped text; ValueError for an impossible date."""
    try:
        ns = rx.receipts.parse_utc_ns(text)
    except ValueError:
        raise _invalid("market_time") from None
    if ns % 1_000_000 or rx.book.replay_market_time(text) != text:
        raise _invalid("market_time")
    return ns // 1_000_000


def iso_ms(ms):
    """2015-06-01T14:00:00.000Z for a pt in ms."""
    moment = _EPOCH + datetime.timedelta(milliseconds=ms)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


@dataclasses.dataclass(frozen=True)
class _Plan:
    """Everything fixed before the first message; the message process draws from its own seeded stream."""

    flow_seed: str
    true_p: tuple           # each runner's chance of winning (the winner is drawn from these)
    q0: tuple               # opening market probabilities: true_p ** alpha renormalised, alpha < 1
    act: tuple              # liquidity and activity weight per runner (favourite 1.0)
    base: tuple             # spread at the off, in ticks
    extra: tuple            # extra spread ticks far from the off
    depth: tuple            # near levels kept each side
    tail_back: tuple        # ((ladder index, size in pence), ...) far offers to back
    tail_lay: tuple
    l_final_p: int          # near-level size scale at the off, pence
    winner: int
    removed: object         # runner index or None
    suspension: object      # (pt, reopen pt) or None
    removal: object         # (pt, reopen pt) or None
    nonfinite: object       # (pt, end pt, runner index) or None
    sp_window_ms: int
    version_base: int
    clk_base: int
    win_bonus: float
    published: bool        # whether definitions carry marketTime


@dataclasses.dataclass(frozen=True)
class Market:
    """One generated market. lines() and messages() replay it from the start on every call."""

    spec: Spec
    market_id: str
    event_id: str
    selection_ids: tuple
    runner_names: tuple
    market_time_ms: int     # the scheduled off on this market's timeline (published or not)
    market_time: object     # the marketTime text the stream publishes, or None under no_market_time
    market_name: str
    event_name: str
    venue: str
    month: str              # YYYY-MM of market_time_ms (UTC)
    start_pt: int           # the first message (the opening image)
    off_pt: int             # the in-play flip (== market_time_ms)
    suspend_pt: int         # the end of the race
    close_pt: int           # CLOSED, the last message
    winner_id: int          # test oracle only
    removed_ids: tuple      # test oracle only
    plan: _Plan = dataclasses.field(repr=False, compare=False)

    def lines(self):
        """Each message as compact JSON bytes (ASCII, no newline), in file order."""
        return _Simulation(self).run()

    def messages(self):
        """Each message parsed (json.loads of lines())."""
        for line in self.lines():
            yield json.loads(line)


def generate(spec):
    """The Market of spec; deterministic for equal specs."""
    if not isinstance(spec, Spec):
        raise TypeError("generate takes a Spec")
    text = "betangel-suite/synthetic/v%d|%d|%d|%d|%d|%s|%s" % (
        GENERATOR_VERSION, spec.seed, spec.runners, spec.pre_off_s, spec.inplay_s, spec.market_time,
        ",".join(sorted(spec.options)))
    rng = random.Random(text + "|structure")
    n = spec.runners
    number = spec.seed % 1_000_000
    market_id = "%s%06d" % (MARKET_ID_PREFIX, number)
    event_id = "%s%06d" % (EVENT_ID_PREFIX, number)
    selection_ids = tuple(rng.sample(range(SELECTION_ID_MIN, SELECTION_ID_MAX + 1), n))
    names = tuple(RUNNER_PREFIX + str(i + 1) for i in range(n))
    off = _time_ms(spec.effective_market_time())
    start = off - spec.pre_off_s * 1000
    suspend = off + spec.inplay_s * 1000
    close = suspend + rng.randint(20_000, 60_000)

    sigma = rng.uniform(0.75, 1.25)
    true_p = _softmax([sigma * rng.normalvariate(0.0, 1.0) for _ in range(n)])
    alpha = rng.uniform(0.82, 0.92)                    # < 1: longshots are overbet (favourite-longshot bias)
    q0 = _softmax([alpha * math.log(p) for p in true_p])
    favourite = max(range(n), key=lambda i: (q0[i], -i))
    removed = None
    if "removal" in spec.options:
        removed = rng.choice([i for i in range(n) if i != favourite])
    others = [i for i in range(n) if i != removed]
    winner = rng.choices(others, weights=[true_p[i] for i in others])[0]
    top = max(q0)
    act = tuple(max(0.05, (q / top) ** 0.6) for q in q0)
    base = tuple(1 if q >= 0.05 else 2 for q in q0)
    extra = tuple(2 if q >= 0.2 else 3 if q >= 0.08 else 5 if q >= 0.03 else 8 for q in q0)
    depth = tuple(rng.randint(8, 14) for _ in range(n))
    tail_back, tail_lay = [], []
    for i in range(n):
        best = _target_index(1.0 / q0[i], base[i] + extra[i])
        tail_back.append(_tail(rng, range(0, max(0, best - depth[i] - 1)), rng.randint(18, 45), 0,
                               (50_00, 2_000_00)))
        tail_lay.append(_tail(rng, range(min(_TOP, best + base[i] + extra[i] + depth[i] + 1), _TOP), rng.randint(20, 55),
                              _TOP, (2_00, 200_00)))
    span = spec.pre_off_s * 1000
    suspension = removal = nonfinite = None
    if "suspension" in spec.options:
        at = start + int(span * rng.uniform(0.20, 0.30))
        suspension = (at, at + max(1, min(int(span * 0.08), rng.randint(5_000, 30_000))))
    if "removal" in spec.options:
        at = start + int(span * rng.uniform(0.45, 0.55))
        removal = (at, at + max(1, min(int(span * 0.05), rng.randint(3_000, 10_000))))
    if "nonfinite_sp" in spec.options:
        at = start + int(span * rng.uniform(0.68, 0.72))
        who = rng.choice([i for i in range(n) if i != removed])
        nonfinite = (at, at + max(1, min(int(span * 0.15), rng.randint(10_000, 40_000))), who)
    plan = _Plan(
        flow_seed=text + "|flow", true_p=tuple(true_p), q0=tuple(q0), act=act, base=base, extra=extra, depth=depth,
        tail_back=tuple(tail_back), tail_lay=tuple(tail_lay),
        l_final_p=int(math.exp(rng.uniform(math.log(300), math.log(4000)))) * 100,
        winner=winner, removed=removed, suspension=suspension, removal=removal, nonfinite=nonfinite,
        sp_window_ms=rng.randint(1800, 7200) * 1000, version_base=rng.randrange(1_000_000_000, 2_000_000_000),
        clk_base=rng.randrange(3_000_000_000, 3_900_000_000), win_bonus=rng.uniform(6.0, 8.0),
        published="no_market_time" not in spec.options)
    moment = _EPOCH + datetime.timedelta(milliseconds=off)
    day = moment.day
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    published = iso_ms(off)
    return Market(
        spec=spec, market_id=market_id, event_id=event_id, selection_ids=selection_ids, runner_names=names,
        market_time_ms=off, market_time=published if plan.published else None,
        market_name="Synthetic %s %s" % (rng.choice(_DISTANCES), rng.choice(_RACE_KINDS)),
        event_name="%s %d%s %s" % (VENUE, day, suffix, _MONTH_NAMES[moment.month - 1]), venue=VENUE,
        month=published[:7], start_pt=start, off_pt=off, suspend_pt=suspend, close_pt=close,
        winner_id=selection_ids[winner], removed_ids=() if removed is None else (selection_ids[removed],), plan=plan)


def _softmax(values):
    top = max(values)
    weights = [math.exp(v - top) for v in values]
    total = sum(weights)
    return [w / total for w in weights]


def _tail(rng, population, count, anchor, size_range):
    """Far offers: the anchor price (1.01 or 1000) and up to count others from population, small sizes."""
    picked = set(rng.sample(population, min(count, len(population)))) if len(population) else set()
    picked.add(anchor)
    low, high = size_range
    found = []
    for index in sorted(picked):
        if index == anchor:
            size = int(math.exp(rng.uniform(math.log(low), math.log(high))))
        else:
            size = int(math.exp(rng.uniform(math.log(2_00), math.log(40_00))))
        found.append((index, max(1, size)))
    return tuple(found)


def _target_index(price, spread):
    """The best back ladder index for a fair decimal price, leaving room for the lay side above it."""
    hundredths = min(_LADDER[-1], max(_LADDER[0], int(price * 100)))
    index = rx.ticks.tick_index(rx.ticks.snap(hundredths, "down"))
    return max(0, min(index, _TOP - spread))


def _closeness(ms_to_off):
    """0 far from the off, 0.6 at T-10m, 1 at the off."""
    return 1.0 / (1.0 + max(0, ms_to_off) / 900_000)


def _rate(ms_to_off):
    """Messages a second before the off (DESIGN.md 6.7 aggregates)."""
    s = ms_to_off / 1000
    if s >= 7200:
        return 0.12
    if s >= 1800:
        return 0.12 + 1.38 * (7200 - s) / 5400
    if s >= 600:
        return 1.5 + 3.5 * (1800 - s) / 1200
    return 5.0 + 5.0 * (600 - s) / 600


_INPLAY_RATE = 12.0


def _price(index):
    """A ladder price as the stream writes it: an int when whole (1000), else a 2 dp float (2.5)."""
    hundredths = _LADDER[index]
    return hundredths // 100 if hundredths % 100 == 0 else hundredths / 100


def _money(pence):
    return pence // 100 if pence % 100 == 0 else pence / 100


class _Runner:
    __slots__ = ("i", "sel", "atb", "atl", "trd", "tv", "ltp", "spn", "spf", "spb", "spl", "u", "last_pt", "removed",
                 "af", "removal_date", "bsp", "w0", "drift", "act", "depth", "tail_back", "tail_lay")

    def __init__(self, i, sel, plan):
        self.i, self.sel = i, sel
        self.atb, self.atl, self.trd, self.spb, self.spl = {}, {}, {}, {}, {}
        self.tv, self.ltp, self.spn, self.spf = 0, None, None, None
        self.u = math.log(plan.q0[i])
        self.last_pt = None
        self.removed = False
        self.af = round(max(0.01, 100 * plan.q0[i]), 2)
        self.removal_date = self.bsp = None
        self.w0 = self.drift = 0.0
        self.act, self.depth = plan.act[i], plan.depth[i]
        self.tail_back, self.tail_lay = frozenset(x for x, _ in plan.tail_back[i]), frozenset(
            x for x, _ in plan.tail_lay[i])


class _Simulation:
    """The message process of one market: a generator of lines, deterministic from the plan's flow seed."""

    def __init__(self, market):
        self.m = market
        self.p = market.plan
        self.rng = random.Random(self.p.flow_seed)
        self.version = self.p.version_base
        self.clk = self.p.clk_base
        self.runners = [_Runner(i, sel, self.p) for i, sel in enumerate(market.selection_ids)]
        self.total = sum(math.exp(r.u) for r in self.runners)
        self.burst = 0
        self.reconciled = False
        self.inplay = False
        self.changes = {}
        self.nonfinite_active = False
        self.last_race_pt = market.off_pt
        self.chances = {}

    # --- the timeline -------------------------------------------------------------------------------

    def run(self):
        m, p = self.m, self.p
        t = m.start_pt
        self._open(t)
        yield self._image(t)
        scheduled = []
        if p.suspension:
            scheduled.append((p.suspension[0], "suspension"))
        if p.removal:
            scheduled.append((p.removal[0], "removal"))
        if p.nonfinite:
            scheduled += [(p.nonfinite[0], "nonfinite_on"), (p.nonfinite[1], "nonfinite_off")]
        scheduled.sort()
        t = self._next(t)
        while t < m.off_pt or scheduled:                # every scheduled pt lies before the off
            if scheduled and scheduled[0][0] <= t:
                at, kind = scheduled.pop(0)
                if kind == "suspension":
                    yield self._suspend_message(at)
                    t = p.suspension[1]
                    yield self._image(t)
                elif kind == "removal":
                    yield self._removal_message(at)
                    t = p.removal[1]
                    self._reprice_after_removal(t)
                    yield self._image(t)
                else:
                    yield self._nonfinite_message(at, kind == "nonfinite_on")
                    t = at
                t = self._next(t)
                continue
            line = self._pre_off_message(t)
            if line is not None:
                yield line
            t = self._next(t)
        yield self._flip(m.off_pt)
        t = self._next(m.off_pt)
        while t < m.suspend_pt:
            line = self._in_play_message(t)
            if line is not None:
                yield line
            t = self._next(t)
        self.version += self.rng.randint(1, 9)
        yield self._encode(m.suspend_pt, self._definition("SUSPENDED", True), None)
        self.version += self.rng.randint(1, 9)
        yield self._encode(m.close_pt, self._definition("CLOSED", True, settled=m.close_pt), None)

    def _next(self, t):
        """The pt of the next message: exponential gaps at the phase's rate, short bursts near the off."""
        rng = self.rng
        to_off = self.m.off_pt - t
        if self.burst:
            self.burst -= 1
            return t + rng.randint(15, 70)
        rate = _INPLAY_RATE if to_off <= 0 else _rate(to_off)
        if to_off < 900_000 and rng.random() < 0.012:
            self.burst = rng.randint(5, 13)
        if rng.random() < 0.02:
            return t                                    # a second message in the same pt batch
        return t + int(rng.expovariate(rate) * 1000)

    # --- state helpers ------------------------------------------------------------------------------

    def _active(self):
        return [r for r in self.runners if not r.removed]

    def _q(self, r):
        return math.exp(r.u) / self.total

    def _touch(self, r):
        found = self.changes.get(r.sel)
        if found is None:
            found = self.changes[r.sel] = {"atb": {}, "atl": {}, "spb": {}, "spl": {}, "trd": {}}
        return found

    def _set(self, r, field, index, size):
        book = getattr(r, field)
        if size > 0:
            book[index] = size
        else:
            book.pop(index, None)
        self._touch(r)[field][index] = max(0, size)

    def _add(self, r, field, index, size):
        """Add size at index unless that would cross the other side; True when added."""
        if field == "atb" and r.atl and index >= min(r.atl):
            return False
        if field == "atl" and r.atb and index <= max(r.atb):
            return False
        if not 0 <= index <= _TOP or size <= 0:
            return False
        self._set(r, field, index, getattr(r, field).get(index, 0) + size)
        return True

    def _trade(self, r, field, index, size):
        """Someone takes size at the best price index of field (atb: a back bet, atl: a lay bet).

        trd and tv count it twice: the PRO historical basis is backer's stake x 2 (F60; module docstring).
        """
        level = getattr(r, field).get(index, 0)
        size = min(size, level, (TV_CAP_P - r.tv) // 2)
        if size <= 0:
            return False
        self._set(r, field, index, level - size)
        r.trd[index] = r.trd.get(index, 0) + 2 * size
        r.tv += 2 * size
        r.ltp = index
        found = self._touch(r)
        found["trd"][index] = r.trd[index]
        found["ltp"] = index
        found["tv"] = r.tv
        return True

    def _trade_size(self, level):
        if self.rng.random() < 0.25:
            return level
        return max(1, int(level * self.rng.uniform(0.03, 0.6)))

    def _level_size(self, k, liquidity):
        shape = (0.55 + 0.18 * k) * math.exp(-k / 6.0)
        return max(1, min(50_000_000, int(liquidity * shape * self.rng.lognormvariate(0.0, 0.7))))

    def _liquidity(self, r, t):
        if self.inplay:
            return 0.3 * self.p.l_final_p * r.act
        c = _closeness(self.m.off_pt - t)
        return self.p.l_final_p * r.act * (0.015 + 0.985 * c ** 1.5)

    def _spread(self, r, t):
        c = _closeness(self.m.off_pt - t)
        return self.p.base[r.i] + int(round(self.p.extra[r.i] * (1.0 - c)))

    def _pre_off_target(self, r, t):
        """Walk the runner's log-strength (volatility rising towards the off); the target best back index."""
        if r.last_pt is not None and t > r.last_pt:
            c = _closeness(self.m.off_pt - t)
            sigma = (0.0015 + 0.008 * c) * math.sqrt((t - r.last_pt) / 1000)
            old = r.u
            r.u += self.rng.normalvariate(0.0, sigma)
            self.total += math.exp(r.u) - math.exp(old)
        r.last_pt = t
        return _target_index(1.0 / self._q(r), self._spread(r, t))

    # --- ladders ------------------------------------------------------------------------------------

    def _rebuild(self, r, best, spread, depth, liquidity, fill=0.8):
        """Move the touch to best (back) and best + spread (lay): clear what would cross, refill the near band."""
        best = max(0, min(best, _TOP - spread))
        lay_best = best + spread
        for index in [x for x in r.atb if x > best]:
            self._set(r, "atb", index, 0)
        for index in [x for x in r.atl if x < lay_best]:
            self._set(r, "atl", index, 0)
        for k in range(depth):
            if best - k >= 0 and (k == 0 or self.rng.random() < fill) and best - k not in r.atb:
                self._add(r, "atb", best - k, self._level_size(k, liquidity))
            if lay_best + k <= _TOP and (k == 0 or self.rng.random() < fill) and lay_best + k not in r.atl:
                self._add(r, "atl", lay_best + k, self._level_size(k, liquidity))

    def _maintain(self, r, depth, liquidity, prune):
        """Keep about depth levels near each touch, and let stale levels away from it decay."""
        rng = self.rng
        for field, sign in (("atb", -1), ("atl", 1)):
            book = getattr(r, field)
            if not book:
                continue
            best = max(book) if field == "atb" else min(book)
            band = [best + sign * k for k in range(depth) if 0 <= best + sign * k <= _TOP]
            empty = [index for index in band if index not in book]
            if len(empty) > len(band) * 0.3 and rng.random() < 0.7:
                index = rng.choice(empty)
                self._add(r, field, index, self._level_size(abs(index - best), liquidity))
            if rng.random() < prune:
                tail = r.tail_back if field == "atb" else r.tail_lay
                stale = [index for index in book if depth < abs(index - best) <= depth + 25 and index not in tail]
                if stale:
                    self._set(r, field, rng.choice(sorted(stale)), 0)

    def _runner_event(self, r, best, spread, liquidity, trade_p, jump):
        """One order-flow event moving the runner's touch towards (best, best + spread)."""
        rng = self.rng
        if not r.atb or not r.atl or abs(max(r.atb) - best) > jump:
            self._rebuild(r, best, spread, r.depth if not self.inplay else 4, liquidity)
            return
        b, l = max(r.atb), min(r.atl)
        x = rng.random()
        if b > best:            # the back price is too long: backers take it, or it is withdrawn
            if not (x < 0.6 and self._trade(r, "atb", b, self._trade_size(r.atb[b]))):
                self._set(r, "atb", b, 0)
            if rng.random() < 0.6:
                self._add(r, "atl", l - 1, self._level_size(0, liquidity))
        elif b < best:          # the back price is too short: layers take the lay side, and backs move up
            if not (x < 0.6 and self._trade(r, "atl", l, self._trade_size(r.atl[l]))):
                self._set(r, "atl", l, 0)
            if rng.random() < 0.6:
                self._add(r, "atb", b + 1, self._level_size(0, liquidity))
        elif l - b > spread and x < 0.5:
            self._add(r, "atl", l - 1, self._level_size(0, liquidity))
        elif l - b < spread and x < 0.3 and len(r.atl) > 1:
            self._set(r, "atl", l, 0)
        elif x < 0.3 + trade_p:
            field = "atb" if rng.random() < 0.5 else "atl"
            index = b if field == "atb" else l
            self._trade(r, field, index, self._trade_size(getattr(r, field)[index]))
        elif x < 0.85:
            field, sign = ("atb", -1) if rng.random() < 0.5 else ("atl", 1)
            k = rng.randrange(r.depth)
            self._add(r, field, (b if field == "atb" else l) + sign * k, self._level_size(k, liquidity))
        else:
            field = "atb" if rng.random() < 0.5 else "atl"
            book = getattr(r, field)
            touch = b if field == "atb" else l
            near = sorted(index for index in book if abs(index - touch) < r.depth)
            if near:
                index = rng.choice(near)
                self._set(r, field, index, int(book[index] * rng.uniform(0.0, 0.8)))
        if not r.atb or not r.atl:
            self._rebuild(r, best, spread, r.depth if not self.inplay else 4, liquidity)
        self._maintain(r, r.depth if not self.inplay else 4, liquidity, 0.3 if self.inplay else 0.08)

    def _sp_update(self, r, t):
        rng = self.rng
        mid = 1.0 / self._q(r)
        r.spn = round(min(1000.0, max(1.01, mid * math.exp(rng.normalvariate(0.0, 0.04)))), 2)
        r.spf = round(min(1000.0, max(1.01, mid * math.exp(rng.normalvariate(0.0, 0.07)))), 2)
        found = self._touch(r)
        found["spn"], found["spf"] = r.spn, r.spf
        if rng.random() < 0.35:
            best = _target_index(mid, self._spread(r, t))
            if rng.random() < 0.5:
                index = max(0, best - rng.randint(0, 6))
                field = "spb"
            else:
                index = min(_SP_LAY_PRICE - 1, best + rng.randint(1, 8))
                field = "spl"
            book = getattr(r, field)
            if index in book and rng.random() < 0.4:
                self._set(r, field, index, 0)
            else:
                self._set(r, field, index, book.get(index, 0) + int(math.exp(rng.uniform(math.log(2_00),
                                                                                         math.log(300_00)))))

    # --- messages -----------------------------------------------------------------------------------

    def _open(self, t):
        """The state at the first message: near bands, far tails, traded history and SP fields."""
        rng = self.rng
        to_off = self.m.off_pt - t
        history = self.p.l_final_p * 40 * _closeness(to_off) ** 2
        for r in self.runners:
            spread = self._spread(r, t)
            best = _target_index(1.0 / self._q(r), spread)
            liquidity = self._liquidity(r, t)
            for index, size in self.p.tail_back[r.i]:
                if index < best - 1:
                    r.atb[index] = size
            for index, size in self.p.tail_lay[r.i]:
                if index > best + spread + 1:
                    r.atl[index] = size
            self._rebuild(r, best, spread, r.depth, liquidity)
            volume = int(history * r.act * rng.uniform(0.5, 1.5))
            if volume >= 2_00:
                weights = {index: rng.uniform(0.2, 1.0) for index in range(max(0, best - 6), min(_TOP, best + 6) + 1)}
                share = sum(weights.values())
                for index, weight in sorted(weights.items()):
                    size = int(volume * weight / share)
                    if size > 0:
                        r.trd[index] = size
                        r.tv += size
                r.ltp = rng.choice([index for index in sorted(r.trd)] or [best])
            r.last_pt = t
            if to_off <= self.p.sp_window_ms:
                self._sp_update(r, t)
        self.changes = {}

    def _image(self, t):
        """img true: the definition and every runner's full state (replaces the market in a cache)."""
        self.version += self.rng.randint(1, 9)
        rc = []
        for r in self.runners:
            entry = {}
            if r.atb:
                entry["atb"] = [[_price(i), _money(s)] for i, s in sorted(r.atb.items(), reverse=True)]
            if r.atl:
                entry["atl"] = [[_price(i), _money(s)] for i, s in sorted(r.atl.items())]
            if r.spn is not None:
                entry["spn"], entry["spf"] = r.spn, r.spf
            if r.spb:
                entry["spb"] = [[_price(i), _money(s)] for i, s in sorted(r.spb.items())]
            if r.spl:
                entry["spl"] = [[_price(i), _money(s)] for i, s in sorted(r.spl.items())]
            if r.trd:
                entry["trd"] = [[_price(i), _money(s)] for i, s in sorted(r.trd.items())]
            if r.ltp is not None and not r.removed:
                entry["ltp"] = _price(r.ltp)
            if r.trd:
                entry["tv"] = _money(r.tv)
            if entry:
                entry["id"] = r.sel
                rc.append(entry)
        self.changes = {}
        change = {"id": self.m.market_id, "marketDefinition": self._definition("OPEN", False), "rc": rc, "img": True}
        return self._line(t, change)

    def _pre_off_message(self, t):
        rng = self.rng
        active = self._active()
        weights = [self.p.q0[r.i] ** 0.5 for r in active]
        count = 1 if rng.random() < 0.7 else 2 if rng.random() < 0.73 else 3
        chosen = []
        for _ in range(min(count, len(active))):
            r = rng.choices(active, weights=weights)[0]
            if r not in chosen:
                chosen.append(r)
        for r in chosen:
            best = self._pre_off_target(r, t)
            self._runner_event(r, best, self._spread(r, t), self._liquidity(r, t), 0.25, 4)
        if self.m.off_pt - t <= self.p.sp_window_ms and rng.random() < 0.06 + 0.1 * _closeness(self.m.off_pt - t):
            r = rng.choices(active, weights=weights)[0]
            if not (self.nonfinite_active and r.i == self.p.nonfinite[2]):
                self._sp_update(r, t)
        rc = self._take_changes()
        return self._encode(t, None, rc) if rc else None

    def _flip(self, t):
        """The off: in play, BSP reconciled, every unmatched offer lapsed, thin in-play ladders."""
        rng = self.rng
        self.inplay = True
        self.reconciled = True
        self.version += rng.randint(1, 9)
        for r in self._active():
            mid = 1.0 / self._q(r)
            r.bsp = round(min(1000.0, max(1.01, mid * math.exp(rng.normalvariate(0.0, 0.03)))), 2)
            r.w0 = math.log(self._q(r))
            r.drift = 0.0
            for field in ("atb", "atl"):
                for index in sorted(getattr(r, field)):
                    self._set(r, field, index, 0)
            for field in ("spb", "spl"):
                for index in sorted(getattr(r, field)):
                    self._set(r, field, index, 0)
        self.last_race_pt = t
        targets = self._race_targets(t)
        for r in self._active():
            best, spread = targets[r.sel]
            liquidity = self._liquidity(r, t)
            if rng.random() < 0.7:
                self._add(r, "atb", 0, int(math.exp(rng.uniform(math.log(2_00), math.log(500_00)))))
            if rng.random() < 0.7:
                self._add(r, "atl", _TOP, int(math.exp(rng.uniform(math.log(2_00), math.log(50_00)))))
            self._rebuild(r, best, spread, 4, liquidity, fill=0.6)
        return self._encode(t, self._definition("OPEN", True), self._take_changes())

    def _race_targets(self, t):
        """Advance the race to t: {selection id: (best back index, spread)} from each runner's chance now."""
        rng = self.rng
        span = self.m.suspend_pt - self.m.off_pt
        progress = min(1.0, max(0.0, (t - self.m.off_pt) / span))
        step = max(0, t - self.last_race_pt) / span
        self.last_race_pt = t
        active = self._active()
        scores = []
        for r in active:
            r.drift += rng.normalvariate(0.0, 0.9 * math.sqrt(step))
            bonus = self.p.win_bonus * progress ** 3 if r.i == self.p.winner else 0.0
            scores.append((1.0 + 5.0 * progress) * (r.w0 + r.drift + bonus))
        chances = _softmax(scores)
        found = {}
        for r, chance in zip(active, chances):
            spread = 1 + (1 if chance < 0.15 else 0) + (2 if chance < 0.03 else 0)
            found[r.sel] = (_target_index(min(1000.0, 1.0 / max(chance, 1e-6)), spread), spread)
        self.chances = dict(zip((r.sel for r in active), chances))
        return found

    def _in_play_message(self, t):
        rng = self.rng
        targets = self._race_targets(t)
        active = self._active()
        weights = [self.chances[r.sel] ** 0.5 + 0.02 for r in active]
        count = 1 if rng.random() < 0.6 else 2 if rng.random() < 0.7 else 3
        chosen = []
        for _ in range(min(count, len(active))):
            r = rng.choices(active, weights=weights)[0]
            if r not in chosen:
                chosen.append(r)
        for r in chosen:
            best, spread = targets[r.sel]
            self._runner_event(r, best, spread, self._liquidity(r, t), 0.45, 2)
        rc = self._take_changes()
        return self._encode(t, None, rc) if rc else None

    def _suspend_message(self, t):
        self.version += self.rng.randint(1, 9)
        return self._encode(t, self._definition("SUSPENDED", False), None)

    def _removal_message(self, t):
        r = self.runners[self.p.removed]
        r.removed = True
        r.removal_date = iso_ms(t)
        r.af = round(max(0.01, 100 * self._q(r)), 2)       # its chance at removal (real semantics unverified)
        self.total -= math.exp(r.u)
        for other in self._active():
            other.af = round(max(0.01, 100 * self._q(other)), 2)
        r.atb.clear()
        r.atl.clear()
        r.spb.clear()
        r.spl.clear()
        r.ltp = r.spn = r.spf = None
        self.version += self.rng.randint(1, 9)
        return self._encode(t, self._definition("SUSPENDED", False), None)

    def _reprice_after_removal(self, t):
        """The rest move to their renormalised prices; unmatched offers near the touch were cancelled."""
        for r in self._active():
            r.last_pt = t
            spread = self._spread(r, t)
            best = _target_index(1.0 / self._q(r), spread)
            liquidity = self._liquidity(r, t) * 0.5
            for field in ("atb", "atl"):
                tail = r.tail_back if field == "atb" else r.tail_lay
                for index in [x for x in getattr(r, field) if x not in tail]:
                    getattr(r, field).pop(index)
            for index in [x for x in r.atb if x >= best]:
                r.atb.pop(index)
            for index in [x for x in r.atl if x <= best + spread]:
                r.atl.pop(index)
            self._rebuild(r, best, spread, r.depth, liquidity)
        self.changes = {}

    def _nonfinite_message(self, t, on):
        r = self.runners[self.p.nonfinite[2]]
        price = _price(_SP_LAY_PRICE)
        self.nonfinite_active = on
        if on:
            r.spn, r.spf = "NaN", "Infinity"
            entry = {"spn": r.spn, "spf": r.spf, "spl": [[price, "Infinity"]], "id": r.sel}
        else:
            mid = 1.0 / self._q(r)
            r.spn = r.spf = round(min(1000.0, max(1.01, mid)), 2)
            entry = {"spn": r.spn, "spf": r.spf, "spl": [[price, 0]], "id": r.sel}
        return self._line(t, {"id": self.m.market_id, "rc": [entry]})

    def _take_changes(self):
        rc = []
        for sel, found in self.changes.items():
            entry = {}
            for field in ("atb", "atl"):
                if found[field]:
                    entry[field] = [[_price(i), _money(s)] for i, s in found[field].items()]
            if "spn" in found:
                entry["spn"], entry["spf"] = found["spn"], found["spf"]
            for field in ("spb", "spl"):
                if found[field]:
                    entry[field] = [[_price(i), _money(s)] for i, s in found[field].items()]
            if found["trd"]:
                entry["trd"] = [[_price(i), _money(s)] for i, s in found["trd"].items()]
            if "ltp" in found:
                entry["ltp"] = _price(found["ltp"])
            if "tv" in found:
                entry["tv"] = _money(found["tv"])
            if entry:
                entry["id"] = sel
                rc.append(entry)
        self.changes = {}
        return rc

    def _definition(self, status, in_play, settled=None):
        m, p = self.m, self.p
        closed = status == "CLOSED"
        runners = []
        for r in self.runners:
            entry = {"adjustmentFactor": r.af}
            if r.removed:
                entry["status"] = "REMOVED"
            elif closed:
                entry["status"] = "WINNER" if r.i == p.winner else "LOSER"
            else:
                entry["status"] = "ACTIVE"
            entry["sortPriority"] = r.i + 1
            if r.removed:
                entry["removalDate"] = r.removal_date
            entry["id"] = r.sel
            entry["name"] = m.runner_names[r.i]
            if self.reconciled and not r.removed:
                entry["bsp"] = r.bsp
            runners.append(entry)
        md = {"bspMarket": True, "turnInPlayEnabled": True, "persistenceEnabled": True, "marketBaseRate": 5,
              "eventId": m.event_id, "eventTypeId": EVENT_TYPE_ID, "numberOfWinners": 1, "bettingType": "ODDS",
              "marketType": "WIN"}
        if p.published:
            md["marketTime"] = md["suspendTime"] = m.market_time
        md.update({"bspReconciled": self.reconciled, "complete": True, "inPlay": in_play, "crossMatching": not in_play,
                   "runnersVoidable": False, "numberOfActiveRunners": len(self._active()),
                   "betDelay": 1 if in_play else 0, "status": status, "priceLadderDefinition": {"type": "CLASSIC"},
                   "runners": runners, "regulators": ["MR_INT"], "venue": m.venue, "countryCode": "GB",
                   "discountAllowed": True, "timezone": "Europe/London"})
        if p.published:
            md["openDate"] = m.market_time
        md.update({"version": self.version, "name": m.market_name, "eventName": m.event_name})
        if settled is not None:
            md["settledTime"] = iso_ms(settled)
        return md

    def _encode(self, t, definition, rc):
        change = {"id": self.m.market_id}
        if definition is not None:
            change["marketDefinition"] = definition
        if rc:
            change["rc"] = rc
        return self._line(t, change)

    def _line(self, t, change):
        self.clk += self.rng.randint(1, 4)
        message = {"op": "mcm", "clk": str(self.clk), "pt": t, "mc": [change]}
        return json.dumps(message, separators=(",", ":"), allow_nan=False).encode("ascii")
