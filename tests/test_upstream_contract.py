"""The upstream contract test (DESIGN.md 4.5; Nuance's answer to Q-N1: "yes, narrowed").

Suite code relies on the exact signatures and behaviour of a few betangel_research names. The pin's per-file
hashes (I-13) say whether a file changed, not whether what the suite relies on still holds, so every pin bump
is gated on this test (DESIGN.md 3.5 item 5). Nuance found that seven injected breaks passed all the other
tests (PR #4 review).

Phase 0's names come first: book.replay_market_time, receipts.parse_utc_ns and the ticks names the suite uses,
with their signatures and their behaviour on small synthetic inputs. The other upstream names Phase 0 code
calls get their signatures and the result shapes the suite reads. Everything is reached through rx, the way
suite code reaches it; this file never imports betangel_research.

CoverageTests fails when suite code uses an rx.<module>.<name> that CONTRACT_NAMES does not list, so each new
upstream name brings its contract with it. The later-phase names of DESIGN.md 4.5 are added as code uses them.
"""

import ast
import inspect
import os
import tempfile
import unittest
from decimal import Decimal

from betangel_suite import rx
from tests.test_ast_boundary import _Checker
from tests.test_imports import python_sources, relative

REQUIRED = "required"
P = "POSITIONAL_OR_KEYWORD"
K = "KEYWORD_ONLY"

# Every upstream name suite code uses, as (rx namespace, name). CoverageTests keeps this complete.
CONTRACT_NAMES = frozenset({
    ("book", "replay_market_time"), ("receipts", "parse_utc_ns"),
    ("ticks", "LADDER_CLASSIC"), ("ticks", "to_hundredths"), ("ticks", "to_pence"), ("ticks", "is_on_ladder"),
    ("ticks", "tick_index"), ("ticks", "snap"),
    ("book", "MarketBookCache"), ("receipts", "strict_json_loads"), ("secret", "register"),
    ("archive", "check_data_root"), ("path_guard", "guard_path"), ("path_guard", "PathDenied"),
})

# 2015-06-01T14:00:00Z, worked out by hand: 16587 days after the epoch, plus 14 hours.
JUNE_1_2PM_NS = (16587 * 86400 + 14 * 3600) * 1_000_000_000


def shape(function):
    """[(name, kind, default or "required")] for each parameter of function."""
    return [(p.name, p.kind.name, REQUIRED if p.default is inspect.Parameter.empty else p.default)
            for p in inspect.signature(function).parameters.values()]


def classic_ladder():
    """Betfair's CLASSIC price increments, typed here independently of upstream's CLASSIC_BANDS, in hundredths."""
    increments = ((101, 200, 1), (200, 300, 2), (300, 400, 5), (400, 600, 10), (600, 1000, 20), (1000, 2000, 50),
                  (2000, 3000, 100), (3000, 5000, 200), (5000, 10000, 500), (10000, 100000, 1000))
    prices = [price for low, high, step in increments for price in range(low, high, step)]
    return tuple(prices + [100000])


def outcome(function, *args):
    """function(*args), or the exception class it raised."""
    try:
        return function(*args)
    except Exception as exc:            # noqa: BLE001 - the class is the result being checked
        return type(exc)


class MarketTimeTests(unittest.TestCase):
    """book.replay_market_time and receipts.parse_utc_ns: engine.market_time_ms and synthetic._time_ms."""

    def test_signatures(self):
        self.assertEqual(shape(rx.book.replay_market_time), [("value", P, REQUIRED)])
        self.assertEqual(shape(rx.receipts.parse_utc_ns), [("text", P, REQUIRED)])

    def test_replay_market_time_passes_whole_millisecond_utc_text_through(self):
        for text in ("2015-06-01T14:00:00.000Z", "2015-06-01T14:00:00Z", "2015-06-01T15:00:00.000+01:00",
                     "2015-06-01T13:00:00.000-01:00", "2015-06-01T14:00:00.123Z", "2015-06-01T14:00:00.123000Z"):
            with self.subTest(text=text):
                self.assertIs(rx.book.replay_market_time(text), text)

    def test_replay_market_time_refuses_with_none(self):
        for value in ("2015-06-01T14:00:00.123456Z",     # finer than a millisecond
                      "2015-06-01T14:00:00.1Z", "2015-06-01T14:00:00.12Z",     # 1 or 2 fraction digits
                      "2015-06-01T14:00:00.000",          # naive
                      "2015-02-30T00:00:00.000Z",          # no such day
                      "2015-06-01T14:00:00.000Z\n", " 2015-06-01T14:00:00.000Z", "2015-06-01 14:00:00.000Z",
                      "２015-06-01T14:00:00.000Z",     # a non-ASCII digit
                      None, 1433167200000, b"2015-06-01T14:00:00.000Z", ["2015-06-01T14:00:00.000Z"]):
            with self.subTest(value=value):
                self.assertIsNone(rx.book.replay_market_time(value))

    def test_replay_market_time_out_of_range_is_none_or_overflow(self):
        # engine._apply_batch catches OverflowError around market_time_ms (Nuance's PR #4 review, item 9), because
        # at the pin replay_market_time catches only ValueError (book.py:68-79). Anything else would end the engine.
        for text in ("0001-01-01T00:00:00.000+23:59", "9999-12-31T23:59:59.999-23:59"):
            with self.subTest(text=text):
                self.assertIn(outcome(rx.book.replay_market_time, text), (None, OverflowError))

    def test_parse_utc_ns_values(self):
        cases = {
            "2015-06-01T14:00:00.000Z": JUNE_1_2PM_NS,
            "2015-06-01T14:00:00Z": JUNE_1_2PM_NS,
            "2015-06-01T15:00:00.000+01:00": JUNE_1_2PM_NS,
            "2015-06-01T13:30:00.000-00:30": JUNE_1_2PM_NS,
            "2015-06-01T14:00:00.5Z": JUNE_1_2PM_NS + 500_000_000,
            "2015-06-01T14:00:00.123Z": JUNE_1_2PM_NS + 123_000_000,
            "2015-06-01T14:00:00.123456Z": JUNE_1_2PM_NS + 123_456_000,
            "1970-01-01T00:00:00.000Z": 0,
            "1969-12-31T23:59:59.999Z": -1_000_000,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                value = rx.receipts.parse_utc_ns(text)
                self.assertIs(type(value), int)
                self.assertEqual(value, expected)

    def test_parse_utc_ns_refuses_with_value_error(self):
        for value in ("2015-06-01T14:00:00.000", "2015-06-01T14:00:00.1234567Z", "2015-02-30T00:00:00.000Z",
                      "2015-06-01T14:00:00.000Z\n", "2015-06-01 14:00:00.000Z", "２015-06-01T14:00:00.000Z", "",
                      None, 1433167200, b"2015-06-01T14:00:00.000Z"):
            with self.subTest(value=value):
                self.assertIs(outcome(rx.receipts.parse_utc_ns, value), ValueError)

    def test_whole_millisecond_text_agrees_with_parse_utc_ns(self):
        # engine.market_time_ms divides parse_utc_ns by 1_000_000 only after replay_market_time accepted the text.
        for text in ("2015-06-01T14:00:00.000Z", "2015-06-01T15:00:00.999+01:00", "2016-02-29T23:59:59.001Z"):
            with self.subTest(text=text):
                self.assertEqual(rx.receipts.parse_utc_ns(rx.book.replay_market_time(text)) % 1_000_000, 0)


class TicksTests(unittest.TestCase):
    """The ticks names: engine.price_h, pence and ladder, synthetic's ladder walk and tools/export_ticks.py."""

    def test_signatures(self):
        self.assertEqual(shape(rx.ticks.to_hundredths), [("value", P, REQUIRED)])
        self.assertEqual(shape(rx.ticks.to_pence), [("value", P, REQUIRED)])
        self.assertEqual(shape(rx.ticks.is_on_ladder), [("price_h", P, REQUIRED)])
        self.assertEqual(shape(rx.ticks.tick_index), [("price_h", P, REQUIRED)])
        self.assertEqual(shape(rx.ticks.snap), [("price_h", P, REQUIRED), ("direction", P, REQUIRED)])

    def test_ladder_is_betfairs_classic_ladder(self):
        ladder = rx.ticks.LADDER_CLASSIC
        self.assertIs(type(ladder), tuple)
        self.assertEqual(len(ladder), 350)
        self.assertTrue(all(type(price) is int for price in ladder))
        self.assertEqual(ladder, classic_ladder())

    def test_exact_conversions(self):
        for convert in (rx.ticks.to_hundredths, rx.ticks.to_pence):
            for value, expected in ((3.45, 345), ("3.45", 345), (Decimal("3.45"), 345), (3, 300), (1.01, 101),
                                    (1000, 100000), (0.1, 10), ("0.10", 10), (-3.45, -345), (0, 0)):
                with self.subTest(convert=convert.__name__, value=value):
                    result = convert(value)
                    self.assertIs(type(result), int)
                    self.assertEqual(result, expected)

    def test_conversions_refuse_with_value_error_only(self):
        # engine.price_h and engine.pence catch ValueError alone: any other exception would end the engine.
        for convert in (rx.ticks.to_hundredths, rx.ticks.to_pence):
            for value in (3.456, "3.456", 2.005, float("nan"), float("inf"), float("-inf"), Decimal("NaN"), 1e300,
                          True, False, None, [1], {"a": 1}, "1e1", "+1", " 1", "1 ", "abc", "", "١"):
                with self.subTest(convert=convert.__name__, value=value):
                    self.assertIs(outcome(convert, value), ValueError)

    def test_is_on_ladder_and_tick_index(self):
        ladder = classic_ladder()
        for index in (0, 1, 98, 99, 100, 158, 209, 210, 348, 349):
            with self.subTest(price=ladder[index]):
                self.assertIs(rx.ticks.is_on_ladder(ladder[index]), True)
                self.assertEqual(rx.ticks.tick_index(ladder[index]), index)
        for value in (100, 201, 346, 1010, 100001, 0, -101, 101.0, 345.0, True, "101", None, Decimal(101)):
            with self.subTest(value=value):
                self.assertIs(rx.ticks.is_on_ladder(value), False)
                self.assertIs(outcome(rx.ticks.tick_index, value), ValueError)

    def test_snap(self):
        for price, direction, expected in ((346, "down", 345), (346, "up", 350), (345, "down", 345), (345, "up", 345),
                                           (201, "down", 200), (201, "up", 202), (199, "up", 199), (100, "up", 101),
                                           (100001, "down", 100000), (99999, "down", 99000), (99999, "up", 100000),
                                           (101, "down", 101), (100000, "up", 100000)):
            with self.subTest(price=price, direction=direction):
                self.assertEqual(rx.ticks.snap(price, direction), expected)
        for price, direction in ((100, "down"), (100001, "up"), (346.0, "down"), (True, "down"), ("346", "down"),
                                 (346, "nearest"), (346, None)):
            with self.subTest(price=price, direction=direction):
                self.assertIs(outcome(rx.ticks.snap, price, direction), ValueError)


class OtherPhase0NameTests(unittest.TestCase):
    """The other upstream names Phase 0 code calls: signatures, and the result shapes the suite reads."""

    def test_market_book_cache_signatures(self):
        cache = rx.book.MarketBookCache
        self.assertEqual(shape(cache.__init__), [("self", P, REQUIRED), ("key_type", K, REQUIRED),
                                                 ("app_key_slot", K, REQUIRED), ("source", K, REQUIRED)])
        self.assertEqual(shape(cache.apply), [("self", P, REQUIRED), ("msg", P, REQUIRED), ("received_at", K, None),
                                              ("monotonic_ns", K, None)])
        self.assertEqual(shape(cache.snapshot), [("self", P, REQUIRED), ("market_id", P, REQUIRED),
                                                 ("unreliable_ok", K, False), ("stamp", K, None)])
        made = cache(key_type="historical", app_key_slot=None, source="recording")     # as engine and synthetic do
        self.assertEqual(made.markets(), [])

    def test_strict_json_loads(self):
        # api/server.py parses request bodies with it: duplicate keys and non-finite numbers are refused.
        self.assertEqual(shape(rx.receipts.strict_json_loads), [("text", P, REQUIRED)])
        self.assertEqual(rx.receipts.strict_json_loads('{"a": [1, 2.5, "x"]}'), {"a": [1, 2.5, "x"]})
        for text in ('{"a": 1, "a": 2}', '{"a": NaN}', "[Infinity]", "[-Infinity]", "1e400", "[" * 100000):
            with self.subTest(text=text[:20]):
                self.assertIs(outcome(rx.receipts.strict_json_loads, text), ValueError)

    def test_secret_register(self):
        self.assertEqual(shape(rx.secret.register), [("value", P, REQUIRED)])

    def test_check_data_root_shape(self):
        # roots._check_suite_root unpacks (resolved, problems) and reads "data_root:<reason>" strings.
        self.assertEqual(shape(rx.archive.check_data_root), [("data_root", P, REQUIRED)])
        base = tempfile.mkdtemp(prefix="contract-")
        self.addCleanup(os.rmdir, base)
        resolved, problems = rx.archive.check_data_root(base)
        self.assertEqual((os.fspath(resolved), problems), (os.path.realpath(base), []))
        _resolved, problems = rx.archive.check_data_root(os.path.join(base, "missing"))
        self.assertEqual(problems, ["data_root:missing"])

    def test_guard_path_shape(self):
        # roots._path_guard catches PathDenied and keeps the reason after the last colon.
        self.assertEqual(shape(rx.path_guard.guard_path), [("path", P, REQUIRED), ("where", P, REQUIRED),
                                                           ("prospective", P, False)])
        self.assertTrue(issubclass(rx.path_guard.PathDenied, Exception))
        base = tempfile.mkdtemp(prefix="contract-")
        self.addCleanup(os.rmdir, base)
        self.assertEqual(os.fspath(rx.path_guard.guard_path(os.path.join(base, "new"), "w", prospective=True)),
                         os.path.join(os.path.realpath(base), "new"))
        for path, prospective, reason in ((base, True, "already_exists"), (os.path.join(base, "gone"), False,
                                                                           "missing_path")):
            with self.subTest(reason=reason):
                with self.assertRaises(rx.path_guard.PathDenied) as caught:
                    rx.path_guard.guard_path(path, "w", prospective=prospective)
                self.assertEqual(str(caught.exception), "w:" + reason)


class CoverageTests(unittest.TestCase):

    def test_every_upstream_name_suite_code_uses_is_under_contract(self):
        used = set()
        for path in python_sources():
            if relative(path) == os.path.join("betangel_suite", "rx.py"):
                continue
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), path)
            checker = _Checker(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
                        and checker.is_rx(node.value.value) and node.value.attr in rx.ALLOWLIST):
                    used.add((node.value.attr, node.attr))
        self.assertTrue(used)
        self.assertEqual(sorted(used - CONTRACT_NAMES), [])

    def test_contract_names_are_allowlisted(self):
        for namespace, name in sorted(CONTRACT_NAMES):
            self.assertIn(name, rx.ALLOWLIST[namespace], namespace)


if __name__ == "__main__":
    unittest.main()
