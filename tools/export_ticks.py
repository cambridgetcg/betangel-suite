"""Export the CLASSIC tick ladder to ui/ticks.json, for the browser ladder (DESIGN.md 8.5, 11).

The UI draws its ladder on the engine's own 350 CLASSIC ticks, in integer hundredths. They come from
rx.ticks.LADDER_CLASSIC (betangel_research.betfair.ticks at the pin, reached only through the suite's pin
and rx), never from a hand-written table. tests/test_ui_assets.py checks that ui/ticks.json equals a
fresh export, so a pin bump that changed the ladder fails until the file is exported again.

The tool prints the JSON on stdout, and the shell writes the file: the guard it runs under (engine mode,
sealed at once) lets no Python code write into the checkout. Run it from the repository root with the
environment bin/suite would give it:

    /usr/bin/env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=en_GB.UTF-8 \\
      TMPDIR="$HOME/.local/state/betangel-suite/tmp" SQLITE_TMPDIR="$HOME/.local/state/betangel-suite/tmp" \\
      BETANGEL_BETFAIR_FORBID_NETWORK=1 PYTHONDONTWRITEBYTECODE=1 \\
      /opt/homebrew/bin/python3.13 -I -S -B tools/export_ticks.py > ui/ticks.json

With --check it writes nothing and exits 0 when ui/ticks.json matches a fresh export, 1 when it does not.
A refusal prints "refused:<code>" on stderr and exits 2. Standard library only; this file never imports
betangel_research itself.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TICKS_JSON = os.path.join(REPO_ROOT, "ui", "ticks.json")
SOURCE = "rx.ticks.LADDER_CLASSIC"
PER_LINE = 16


def render(ladder):
    """The exact bytes of ui/ticks.json for a ladder of strictly ascending int hundredths."""
    ticks = list(ladder)
    if not ticks or any(type(tick) is not int or tick <= 0 for tick in ticks):
        raise ValueError("ladder must hold positive integer hundredths")
    if any(later <= earlier for earlier, later in zip(ticks, ticks[1:])):
        raise ValueError("ladder must be strictly ascending")
    rows = [", ".join(str(tick) for tick in ticks[start:start + PER_LINE])
            for start in range(0, len(ticks), PER_LINE)]
    lines = [
        "{",
        '  "schema_version": 1,',
        '  "ladder": "CLASSIC",',
        '  "unit": "hundredths",',
        '  "source": "%s",' % SOURCE,
        '  "count": %d,' % len(ticks),
        '  "ticks": [',
        ",\n".join("    " + row for row in rows),
        "  ]",
        "}",
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def _refuse(code):
    sys.stderr.write("refused:" + code + "\n")
    return 2


def main(argv):
    if argv not in ([], ["--check"]):
        return _refuse("bad_arguments")
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        return _refuse("launch_flags")          # before any import that could write bytecode
    if REPO_ROOT not in sys.path:
        sys.path.append(REPO_ROOT)
    from betangel_suite import errors, guard            # standard library only; nothing upstream yet
    try:
        guard.arm("engine")
        guard.seal()                    # no subprocess and no new bind permit from here on
        errors.install_excepthooks()
        from betangel_suite import rx
        data = render(rx.ticks.LADDER_CLASSIC)
    except errors.SuiteError as exc:
        sys.stderr.write(errors.describe(exc) + "\n")
        return 2
    if argv == ["--check"]:
        try:
            with open(TICKS_JSON, "rb") as handle:
                current = handle.read()
        except OSError:
            current = None
        if current != data:
            sys.stderr.write("ticks_json: stale\n")
            return 1
        sys.stderr.write("ticks_json: OK\n")
        return 0
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
