"""The only module that imports betangel_research (DESIGN.md 4.1, invariant I-1).

Importing rx requires the armed guard, verifies the pin (pin.activate), imports exactly the modules of
the section 4.1 allowlist from the deps clone, checks that every loaded betangel_research module came
from that clone, and cross-checks upstream's own network switch. Suite code then reaches upstream only
through the namespaces below, each holding only the allowlisted names of one module (rx.ticks.snap,
rx.paper.PaperExchange, ...). Test-only oracles (section 4.2) are imported by tests directly, never here.

validate.make_customer_ref and make_customer_order_ref are exported as wrappers that require the rng
(section 4.1: "Refs come from a deterministic rng per session and click"). Upstream defaults rng to None and
then uses secrets.token_hex (validate.py:40, :46, :51), which would make refs, and so replays, random. Its test
is `rng or secrets.token_hex`, so a callable that is falsy (a tape whose __len__ is 0, say) would fall back to
secrets too: the wrapper passes upstream a lambda calling the rng, which is always truthy, and never draws from
the rng itself (Nuance's PR #2 review, item 9).

call(fn, ...) is the error boundary of section 9.2 item 9: IndexProblem, ArchiveProblem, PathDenied,
JournalError and ValueError become a SuiteError holding a kind code, a listed reason and a salted hash.
The SuiteError is raised outside the except block, so it carries no reference to the original
exception, its message or its traceback.
"""

import types

from . import errors as suite_errors
from . import guard, pin

guard.require_armed()
DEPS = pin.activate()

from betangel_research import evaluation as _evaluation                                   # noqa: E402
from betangel_research.betfair import (book as _book, config as _config, constants as _constants,  # noqa: E402
                                       errors as _errors, journal as _journal, lifecycle as _lifecycle,
                                       paper as _paper, paths as _paths, pnl as _pnl, receipts as _receipts,
                                       schemas as _schemas, secret as _secret, ticks as _ticks,
                                       validate as _validate)
from betangel_research.betfair.backtest import (archive as _archive, contract as _contract,  # noqa: E402
                                                market_index as _market_index, path_guard as _path_guard)

pin.assert_origins(DEPS)
if _paths.FORBID_NETWORK_ENV != guard.FORBID_NETWORK_ENV or not _paths.network_forbidden():
    raise suite_errors.SuiteError("network_not_forbidden")

# The section 4.1 interface table, plus the four exception classes of section 9.2 item 9.
ALLOWLIST = {
    "ticks": ("LADDER_CLASSIC", "parse_money", "parse_price", "to_hundredths", "to_pence", "is_on_ladder",
              "tick_index", "tick_offset", "ticks_between", "snap"),
    "constants": ("MIN_BET_PENCE_GBP", "CLASSIC_BANDS", "MARKET_STATUSES", "COMMISSION_SOURCES",
                  "ABSOLUTE_CEILINGS"),
    "book": ("MarketBookCache", "replay_market_time"),
    "schemas": ("BOOK_SNAPSHOT_KEYS", "RUNNER_KEYS", "SNAPSHOT_KEY_TYPES", "INSTRUCTION_V1_KEYS", "ORDER_STATES",
                "UNRESOLVED_STATES", "validate_book_snapshot", "validate_instruction_v1"),
    "validate": ("validate_place", "validate_cancel", "make_customer_ref", "make_customer_order_ref",
                 "profit_ratio_ok"),
    "paper": ("PaperExchange", "PAPER_MODEL", "PAPER_ASSUMPTIONS", "PARAM_KEYS", "REPLAY_STATUS", "book_time_ms",
              "paper_bet_id"),
    "lifecycle": ("TRANSITIONS", "PAPER_REFUSAL_CODES", "PAPER_FAILED_CODES", "transition",
                  "classify_place_report", "classify_cancel_report"),
    "journal": ("OrderJournal", "JournalFolder", "KINDS", "INTENT_PAYLOAD_KEYS", "INTENT_SOURCES",
                "CLOCK_REGRESSION_NS"),
    "pnl": ("order_pnl_pence", "market_realized", "EXCLUDING_RESULTS"),
    "evaluation": ("settled_market_costs",),
    "config": ("DEFAULTS", "validate_config"),
    "paths": ("FORBID_NETWORK_ENV", "network_forbidden", "overrides_allowed", "StatePaths"),
    "receipts": ("utc_from_ns", "parse_utc_ns", "canonical_sha256", "file_sha256", "atomic_write_json",
                 "append_jsonl", "strict_json_loads"),
    "secret": ("register", "assert_clean", "refuse_forbidden"),
    "betfair_errors": ("JournalError",),
    "archive": ("CHUNK_BYTES", "LIMIT_CEILINGS", "Limits", "DEFAULT_LIMITS", "market_month", "month_gate",
                "parse_member_path", "check_data_root", "HashingReader", "safe_path", "safe_target",
                "ArchiveProblem"),
    "market_index": ("HEAD_FILE", "MARKETS_FILE", "loads_strict", "market_sort_key", "load_manifest",
                     "archive_shas", "IndexProblem"),
    "path_guard": ("guard_path", "PathDenied", "denied_sequence"),
    "contract": ("SEALED_HOLDOUT", "INSPECTED_MONTHS", "EXPOSED_MONTHS", "NOT_PROSPECTIVE_DATES"),
}


def _export(module, key):
    return types.SimpleNamespace(**{name: getattr(module, name) for name in ALLOWLIST[key]})


def _rng_required(make_ref):
    """make_ref(now_ns, rng) with the rng required: a callable taking 8 and returning 16 lowercase hex."""
    def wrapper(now_ns, rng):
        if not callable(rng):
            raise suite_errors.SuiteError("rng_required")
        return make_ref(now_ns, lambda nbytes: rng(nbytes))      # truthy whatever rng's own truth value is

    wrapper.__name__ = wrapper.__qualname__ = make_ref.__name__
    wrapper.__doc__ = make_ref.__doc__
    return wrapper


ticks = _export(_ticks, "ticks")
constants = _export(_constants, "constants")
book = _export(_book, "book")
schemas = _export(_schemas, "schemas")
validate = _export(_validate, "validate")
validate.make_customer_ref = _rng_required(_validate.make_customer_ref)
validate.make_customer_order_ref = _rng_required(_validate.make_customer_order_ref)
paper = _export(_paper, "paper")
lifecycle = _export(_lifecycle, "lifecycle")
journal = _export(_journal, "journal")
pnl = _export(_pnl, "pnl")
evaluation = _export(_evaluation, "evaluation")
config = _export(_config, "config")
paths = _export(_paths, "paths")
receipts = _export(_receipts, "receipts")
secret = _export(_secret, "secret")
betfair_errors = _export(_errors, "betfair_errors")
archive = _export(_archive, "archive")
market_index = _export(_market_index, "market_index")
path_guard = _export(_path_guard, "path_guard")
contract = _export(_contract, "contract")

# Most specific first: ConfigError and ContractFileError are ValueErrors and map as value_error.
MAPPED = (
    (_market_index.IndexProblem, "index_problem"),
    (_archive.ArchiveProblem, "archive_problem"),
    (_path_guard.PathDenied, "path_denied"),
    (_errors.JournalError, "journal_error"),
    (ValueError, "value_error"),
)
_CAUGHT = tuple(cls for cls, _ in MAPPED)


def map_error(exc, *, home_dir=None):
    """The SuiteError for one of the MAPPED exceptions (section 9.2 item 9)."""
    kind, text = _classify(exc)
    return suite_errors.from_upstream(kind, text, home_dir=home_dir)


def call(fn, *args, **kwargs):
    """fn(*args, **kwargs), with the MAPPED upstream exceptions turned into SuiteError at this boundary.

    Only the kind and the message text leave the except block; the SuiteError is built and raised
    outside it, so it carries no __context__, no upstream exception object and no upstream traceback.
    """
    try:
        return fn(*args, **kwargs)
    except _CAUGHT as exc:
        kind, text = _classify(exc)
    raise suite_errors.from_upstream(kind, text)


def _classify(exc):
    kind = next(code for cls, code in MAPPED if isinstance(exc, cls))
    try:
        text = str(exc)
    except Exception:
        text = ""
    return kind, text
