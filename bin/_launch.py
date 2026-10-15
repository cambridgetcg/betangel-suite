"""Entry point behind bin/suite: interpreter check, path setup, guard arming, run-marker check, dispatch.

bin/suite runs this file as `python3.13 -I -S -B bin/_launch.py <command> ...` under env -i. The order
matters and is part of the design (DESIGN.md 3.6, 6.8, 10):

  1. refuse any interpreter but 3.13 and the 3.11 floor (I-14; 3.15 is frozen for Nuance's certification) and
     any start without -I, -S and -B; this prologue uses only old syntax so the refusal is clean;
  2. append the checkout root to sys.path (-I leaves the script's directory off it);
  3. arm the audit hook (betangel_suite.guard) in the mode the command name selects, before anything
     can import betangel_research, and install the code-only exception hooks;
  4. check TMPDIR against roots.tmp_dir(command), then (for every command except stop, test and vendor) load
     the config and refuse while the run marker exists, before anything is created anywhere;
  5. dispatch to betangel_suite.cli, which creates TMPDIR (0700) before any handler runs.

A refusal prints one line, "refused:<code>", on stderr and exits 2.
"""

import os
import sys

ALLOWED_VERSIONS = ((3, 11), (3, 13))               # guard.ALLOWED_VERSIONS holds the same tuple


def interpreter_ok(version):
    return tuple(version[:2]) in ALLOWED_VERSIONS


def flags_ok(flags):
    return bool(flags.isolated and flags.no_site and flags.dont_write_bytecode)


def _refuse(code):
    sys.stderr.write("refused:" + code + "\n")
    return 2


def main(argv):
    if not interpreter_ok(sys.version_info):
        return _refuse("interpreter_version")
    if not flags_ok(sys.flags):
        return _refuse("launch_flags")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.append(root)
    from betangel_suite import cli, errors, guard      # standard library only; nothing upstream yet
    command = argv[0] if argv else ""
    try:
        guard.arm(cli.guard_mode(command))
        errors.install_excepthooks()
        os.umask(0o077)
        try:
            os.nice(10)
        except OSError:                 # already at the maximum niceness: the intent is met
            pass
        from betangel_suite import config, roots, runmarker
        if not command:
            raise errors.SuiteError("no_command")
        if command not in cli.COMMANDS:
            raise errors.SuiteError("unknown_command")
        if os.path.normpath(os.environ.get("TMPDIR", "")) != roots.tmp_dir(command):
            raise errors.SuiteError("tmpdir_mismatch")
        if command not in cli.NO_RUN_MARKER_CHECK:
            runmarker.require_absent(runmarker.marker_path(config.load()))
        return cli.main(argv)
    except errors.SuiteError as exc:
        sys.stderr.write(errors.describe(exc) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
