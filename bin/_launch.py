"""Entry point behind bin/suite: interpreter check, path setup, guard arming, run-marker check, dispatch.

bin/suite runs this file as `python3.13 -I -S -B bin/_launch.py <command> ...` under env -i. The order
matters and is part of the design (DESIGN.md 3.6, 6.8, 10):

  1. refuse any interpreter but 3.13 and the 3.11 floor (I-14; 3.15 is frozen for Nuance's certification) and
     any start without -I, -S and -B; this prologue uses only old syntax so the refusal is clean;
  2. append the checkout root (its real path, so app/current resolves to one release copy) to sys.path (-I
     leaves the script's directory off it);
  3. arm the audit hook (betangel_suite.guard) in the mode the command name selects, before anything
     can import betangel_research, and install the code-only exception hooks;
  4. if the root lies under ~/.local/share/betangel-suite/app, verify it as a release copy against its
     RELEASE.json (betangel_suite.release, I-18) and refuse any mismatch; any other root is a working checkout;
     then check TMPDIR against roots.tmp_dir(command), then (for every command except stop, so test and vendor
     too) load the config and refuse while the run marker exists, before anything is created anywhere;
  5. dispatch to betangel_suite.cli, which, for a command that may touch real data, takes run/realdata.lock shared
     and checks the marker again under it (runmarker.hold_shared), then creates TMPDIR (0700) before any handler
     runs.

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
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
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
        from betangel_suite import config, release, roots, runmarker
        release.check_launch(root)          # a release copy runs only while it matches its RELEASE.json (I-18)
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
