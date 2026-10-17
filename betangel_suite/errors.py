"""Closed error codes, salted identifier hashes and code-only exception hooks (DESIGN.md 9.1, 9.2 item 9).

Everything the suite prints, logs or returns about a failure is a code from CODES, optionally a reason
from UPSTREAM_REASONS and a salted hash; never a path, identifier, data row, exception message or
traceback. Upstream exceptions are mapped at the rx boundary through from_upstream(): only the text after
the last colon survives, and only when it is a listed reason; everything else is replaced by a salted
hash, so equal failures still correlate without the identifier being shown.

The salt is per install: 32 random bytes in a 0600 file at ~/.local/state/betangel-suite/install-salt
(AGENTS.md adaptation B), not under the suite root, although Yu agreed that root (R-4; AGENTS.md adaptation A).
The first process that hashes an identifier makes it, and every guard mode may write the state root, while only
the engine may write the suite root. Moving the salt byte for byte into suite.noindex is lab-Claude's proposal,
asked of Nuance on 2026-10-17, not answered (DESIGN.md 9.2 item 9); if it ever moves, the same bytes must move with
it, or earlier hashes stop matching.

tools/hygiene_scan.py and tools/pre-commit print their own refusal codes (refused:usage, git_failed,
python3.13_missing, ...). They are a separate enum on purpose: the scanner must run without importing
betangel_suite. Every code the launcher and the betangel_suite package print is listed here.

Standard library only; this module never imports betangel_research.
"""

import hashlib
import hmac
import os
import re
import secrets
import stat
import sys
import threading

CODES = frozenset({
    # launcher, interpreter and environment (I-2, I-14)
    "interpreter_version", "launch_flags", "network_not_forbidden", "stray_environment", "home_invalid",
    "tmpdir_mismatch",
    # bin/suite's SSH checks, printed before env -i (DESIGN.md 3.6)
    "ssh_session_outside_ssh", "ssh_original_command", "open_over_ssh", "print_url_over_ssh",
    # the audit hook (I-3..I-6)
    "guard_not_armed", "guard_mode_conflict", "guard_mode_invalid", "guard_sealed", "guard_internal_error",
    "network_refused", "name_lookup_refused", "bind_refused", "bind_permit_invalid", "subprocess_refused",
    "dlopen_refused", "write_outside_roots", "state_root_not_agreed", "environment_change_refused",
    "root_replace_refused", "sqlite_connect_refused", "sqlite_limit_refused", "import_refused",
    "module_loaded_early", "call_replaced_early", "listen_refused", "run_lock_protected", "data_home_read_refused",
    # commands
    "no_command", "unknown_command", "not_implemented", "bad_arguments", "state_root_changed",
    # the run marker and the realdata lock (I-17)
    "run_marker_present", "run_marker_unreadable", "run_lock_busy", "run_lock_invalid", "run_lock_not_held",
    # suite config
    "config_unreadable", "config_insecure", "config_too_large", "config_not_json", "config_not_object",
    "config_unknown_key", "config_invalid_value",
    # the pin (I-13) and the vendor tool
    "pin_invalid", "pin_mismatch", "deps_missing", "deps_bytecode_present", "deps_shadow_present",
    "research_clone_on_path", "upstream_imported_early", "upstream_origin_mismatch", "upstream_import_refused",
    "commit_not_present", "commit_not_on_main", "partial_exists", "git_failed", "deps_link_present",
    # roots and the writer helper
    "path_not_absolute", "already_exists", "not_a_directory", "symlink_refused", "wrong_owner",
    "root_parent_missing", "write_failed", "salt_invalid", "suite_root_invalid", "suite_root_misplaced",
    "root_overlaps_data_home", "root_overlaps_lab_runs",
    # upstream exception kinds mapped at the rx boundary, and rx's own argument checks
    "index_problem", "archive_problem", "path_denied", "journal_error", "value_error", "rng_required",
    # a code that is not listed here is reported as this
    "unlisted_code",
})

# Reasons upstream puts after the last colon of IndexProblem, ArchiveProblem, PathDenied, JournalError and
# ValueError (including ConfigError and ContractFileError) at the pin. tests/test_errors.py re-extracts them
# from the pinned sources (every construction of those classes, not only raise statements, plus the string
# constants that reach a dynamic tail), so a pin bump that adds one fails loudly until it is reviewed and
# listed here.
UPSTREAM_REASONS = frozenset({
    # backtest/archive.py ArchiveProblem (not_bz2 is built, then raised, at archive.py:427; market_index.py
    # also records it as a member's unreadable reason)
    "changed_during_ingest", "compression_ratio_over_limit", "decompressed_too_large", "empty_member",
    "extended_header_chain", "extended_header_too_large", "not_bz2", "not_regular", "partial_file_present",
    "pax_global_header", "target_exists", "total_decompressed_over_limit", "truncated_bz2", "unsafe_target",
    "write_failed",
    # backtest/archive.py check_data_root problems ("data_root:<reason>"; missing, not_a_directory and
    # unreadable are listed elsewhere), used on the suite root (roots.py)
    "inside_git_worktree", "inside_repository",
    # backtest/market_index.py IndexProblem
    "malformed", "member_hash_mismatch", "member_inconsistent", "missing", "names_another_archive",
    "not_a_directory", "not_canonical", "not_json", "unreadable", "unsupported", "gate_changed",
    "index_would_change",
    # backtest/path_guard.py PathDenied
    "already_exists", "denied_live_state_tree", "missing_path", "not_one_name", "parent_not_a_directory",
    "unresolvable",
    # backtest/contract.py ContractFileError
    "duplicate_key", "non_finite_number", "not_a_regular_file", "not_utf8", "number_too_large", "too_large",
    # betfair/journal.py and lifecycle.py JournalError
    "account_fingerprint_invalid", "account_fingerprint_mismatch", "customer_order_ref_reused",
    "expect_head_invalid", "final_state_size_unaccounted", "fold_now_ns_must_be_integer",
    "intent_builds_invalid_order_record", "intent_columns_incomplete", "intent_flags_must_be_boolean",
    "intent_instruction_invalid", "intent_payload_keys_must_be_exact", "intent_provisional_child_needs_parent_ref",
    "intent_source_invalid", "intent_strategy_ref_invalid", "journal_busy_timeout_invalid",
    "journal_committed_event_unfoldable", "journal_event_mode_mismatch", "journal_event_unfoldable",
    "journal_halts_invalid", "journal_head_moved", "journal_head_moved_during_fold", "journal_integrity_error",
    "journal_kind_invalid", "journal_mode_invalid", "journal_mode_mismatch", "journal_payload_must_be_object",
    "journal_payload_not_strict_json", "journal_schema_incomplete", "journal_schema_version_mismatch",
    "journal_state_after_needs_customer_order_ref", "journal_transactions_invalid",
    "journal_transition_shape_invalid", "journal_transitions_must_be_list", "journal_unreadable",
    "journal_wal_unavailable", "lapsed_with_matched_size_use_execution_complete", "paper_state_in_live_journal",
    "paper_state_invalid", "replace_child_differs_from_parent", "replace_child_parent_not_replaceable",
    "replace_child_without_parent", "resume_cleared_through_seq_invalid", "resume_market_scope_needs_market_id",
    "resume_scope_invalid", "settle_basis_invalid", "settle_commission_p_must_be_non_negative_integer",
    "settle_echo_invalid", "settle_market_status_invalid", "settle_shown_sha256_invalid", "since_seq_invalid",
    # state_after is a journal column name, the literal tail of journal.py:284
    # JournalError("journal_column_invalid:state_after"). It is kept because it names a schema column (never
    # data) and makes that one failure specific; journal.py:155's journal_column_invalid:{name} maps every
    # other column to unlisted_reason.
    "state_after", "submit_action_invalid", "submit_body_sha256_invalid", "submit_instruction_count_invalid",
    "transition_field_not_mutable", "transition_for_unknown_order", "transition_produces_invalid_order_record",
    "transition_reason_invalid", "unknown_order_state",
    # betfair/config.py, paths.py and filters.py ConfigError (a ValueError)
    "account_currency_must_be_iso_code", "api_host_must_be_api_betfair_com_for_jurisdiction", "config_missing",
    "config_not_strict_json", "config_override_not_allowed", "config_profile_does_not_match_state_profile",
    "config_unreadable", "invalid_journal_mode", "invalid_profile", "market_data_filter_ex_best_offers_disp_refused",
    "market_data_filter_ex_market_def_required", "market_data_filter_fields_must_be_unique_strings",
    "market_data_filter_ladder_levels_above_3_not_motif_compatible",
    "market_data_filter_ladder_levels_out_of_range", "market_filter_empty", "market_filter_must_be_object",
    "market_start_window_reversed", "money_must_be_finite_number", "money_must_be_positive",
    "money_must_have_at_most_2dp", "money_out_of_range", "motif_compatible_must_be_boolean",
    "schema_version_must_be_1", "state_root_override_not_allowed", "stream_live_key_needs_recorder_allow_live_key",
    # coded ValueErrors (book.py, paper.py, validate.py, market_index.py and others)
    "incomplete_runner_definition", "market_bet_delay_missing", "market_definition_missing",
    "market_in_play_missing", "market_status_missing_or_unknown", "missing_or_invalid_active_runner_prices",
    "missing_snapshot", "not_open_preplay", "outside_declared_population",
    "recordings_mix_known_and_unknown_gap_windows", "runner_set_changed", "scheduled_start_revised",
    "stale_market_snapshot", "stream_unreliable", "unknown_market",
})

UNLISTED_CODE = "unlisted_code"
UNLISTED_REASON = "unlisted_reason"
SALT_BYTES = 32
_REF_RE = re.compile(r"h[0-9a-f]{16}")
_CLASS_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


class SuiteError(Exception):
    """A refusal or failure; str() is "<code>[:<reason>][ ref=<hash>]" and never carries data.

    A code outside CODES becomes unlisted_code and a reason outside UPSTREAM_REASONS becomes
    unlisted_reason, so a programming slip can never turn caller text into output.
    """

    def __init__(self, code, reason=None, ref=None):
        code = code if code in CODES else UNLISTED_CODE
        if reason is not None and reason not in UPSTREAM_REASONS:
            reason = UNLISTED_REASON
        if ref is not None and not (isinstance(ref, str) and _REF_RE.fullmatch(ref)):
            ref = None
        super().__init__(code)
        self.code, self.reason, self.ref = code, reason, ref

    def __str__(self):
        text = self.code if self.reason is None else f"{self.code}:{self.reason}"
        return text if self.ref is None else f"{text} ref={self.ref}"


def from_upstream(kind, text, *, home_dir=None):
    """The SuiteError for an upstream exception of the given kind (a CODES entry) whose str() is text.

    Only the part after the last colon is kept, and only if it is a listed reason. Whatever else the text
    held (the "where" label, or the whole text when the reason is not listed) becomes one salted hash.
    """
    where, _, tail = text.rpartition(":")
    reason = tail if tail in UPSTREAM_REASONS else UNLISTED_REASON
    hidden = where if reason != UNLISTED_REASON else text
    return SuiteError(kind, reason, salted_hash(hidden, home_dir=home_dir) if hidden else None)


# --- salted identifier hashes ----------------------------------------------------------------------

_SALTS = {}
_SALT_LOCK = threading.Lock()


def salted_hash(identifier, *, home_dir=None):
    """"h" + 16 hex characters of HMAC-SHA256(install salt, identifier); stable per install."""
    if isinstance(identifier, bytes):
        data = identifier
    else:
        data = str(identifier).encode("utf-8", "surrogateescape")
    return "h" + hmac.new(_salt(home_dir), data, hashlib.sha256).hexdigest()[:16]


def _salt(home_dir):
    from . import roots            # here, not at the top: roots imports this module
    path = roots.salt_path(home_dir)
    with _SALT_LOCK:
        salt = _SALTS.get(path)
        if salt is None:
            salt = _read_salt(path)
            if salt is None:
                try:
                    roots.write_new(path, secrets.token_bytes(SALT_BYTES), home_dir=home_dir)
                except SuiteError as exc:
                    if exc.code != "already_exists":       # another process won the race: read its salt
                        raise
                salt = _read_salt(path)
                if salt is None:
                    raise SuiteError("salt_invalid")
            _SALTS[path] = salt
        return salt


def _read_salt(path):
    """The salt bytes, None when the file does not exist; SuiteError(salt_invalid) for anything odd.

    The open is O_NONBLOCK and fstat judges the file before anything is read, so a FIFO (or a directory) in the
    salt's place is refused at once: a blocking open of a FIFO would wait for a writer for ever (Nuance's PR #2
    review, item 22).
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError:
        fd = None
    if fd is None:
        raise SuiteError("salt_invalid")
    data = None
    try:
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077:
            data = os.read(fd, SALT_BYTES + 1)
    finally:
        os.close(fd)
    if data is None or len(data) != SALT_BYTES:
        raise SuiteError("salt_invalid")
    return data


# --- code-only exception hooks ---------------------------------------------------------------------

def describe(exc):
    """One output line for an exception: "refused:<code...>" or "error:<class name>", nothing else."""
    if isinstance(exc, SuiteError):
        return "refused:" + str(exc)
    name = type(exc).__name__
    return "error:" + (name if _CLASS_RE.fullmatch(name) else "Exception")


def _excepthook(exc_type, exc, tb):
    sys.stderr.write(describe(exc) + "\n")


def _thread_excepthook(args):
    if args.exc_type is SystemExit:
        return
    sys.stderr.write("thread:" + describe(args.exc_value) + "\n")


def _unraisablehook(unraisable):
    sys.stderr.write("unraisable:" + describe(unraisable.exc_value) + "\n")


def install_excepthooks():
    """Replace the hooks that would print tracebacks or exception messages (DESIGN.md 9.1).

    Phase 0 writes full tracebacks nowhere. They belong in the suite root's private/ directory, which
    nothing writes yet.
    """
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    sys.unraisablehook = _unraisablehook
