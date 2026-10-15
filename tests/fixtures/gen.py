"""Synthetic PRO members, member trees and TARs, written at test time into a temp dir (DESIGN.md 4.2, 11).

A member is one market's stream (betangel_suite.synthetic), newline-terminated lines, bz2-compressed, at the
documented member path PRO/<YYYY>/<Mon>/<D>/<eventId>/<marketId>.bz2 (archive.MEMBER_LAYOUT; the date is the
market's scheduled off in UTC, the day without a leading zero). A TAR holds members only (no directory entries),
with fixed header fields, so equal inputs give equal bytes and equal archive hashes.

standard_archive() is the one the data tests ingest and index: four markets in 2015-05 (the engineering year), one
each with no option, suspension plus removal, nonfinite_sp, and no_market_time. gated_archive() adds the months the
month gate refuses (DESIGN.md I-11: 2026-01, 2026-09, 2026-10, 2027-01) and a member whose path says 2015-05 while
its marketTime says 2026-01 (refused by archive.py's content scan).

Callers own the directory: make it with tempfile under TMPDIR (bin/suite test points TMPDIR at the state root's
tmp/) and remove it afterwards. Nothing here reads or writes anywhere else, and nothing here imports upstream.
"""

import bz2
import dataclasses
import io
import os
import tarfile

from betangel_suite import synthetic

PLAN = "PRO"
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TAR_MTIME = 1_431_000_000             # fixed header time (2015-05-07), so TAR bytes depend on content only
STANDARD_MONTH = "2015-05"
GATED_MONTHS = ("2026-01", "2026-09", "2026-10", "2027-01")

# Small markets: about 1,000-3,000 messages each, so ingest and index stay fast.
STANDARD_SPECS = (
    synthetic.Spec(seed=101, runners=6, pre_off_s=300, inplay_s=30, market_time="2015-05-02T14:00:00.000Z"),
    synthetic.Spec(seed=102, runners=9, pre_off_s=240, inplay_s=30, market_time="2015-05-02T14:35:00.000Z",
                   options=frozenset({"suspension", "removal"})),
    synthetic.Spec(seed=103, runners=5, pre_off_s=180, inplay_s=20, market_time="2015-05-16T15:10:00.000Z",
                   options=frozenset({"nonfinite_sp"})),
    synthetic.Spec(seed=104, runners=5, pre_off_s=120, inplay_s=20, market_time="2015-05-30T13:00:00.000Z",
                   options=frozenset({"no_market_time"})),
)


@dataclasses.dataclass(frozen=True)
class Member:
    path: str                       # the member path inside the TAR (and under raw/<sha>/ after ingest)
    market: synthetic.Market
    data: bytes                     # the bz2 bytes


@dataclasses.dataclass(frozen=True)
class Archive:
    path: str                       # the TAR file
    members: tuple                  # Member, in TAR order


def member_path(market, *, plan=PLAN, date=None):
    """PRO/YYYY/Mon/D/<eventId>/<marketId>.bz2 for the market's scheduled off (UTC), or for date (YYYY-MM-DD)
    when the path must disagree with the content (content-gate tests)."""
    if date is None:
        date = synthetic.iso_ms(market.market_time_ms)[:10]
    year, month, day = date.split("-")
    return "%s/%s/%s/%d/%s/%s.bz2" % (plan, year, MONTH_NAMES[int(month) - 1], int(day), market.event_id,
                                      market.market_id)


def member_text(market):
    """The decompressed member: every line, each ending in a newline."""
    return b"".join(line + b"\n" for line in market.lines())


def member_bytes(market):
    return bz2.compress(member_text(market), 9)


def member(market, *, plan=PLAN, date=None):
    return Member(member_path(market, plan=plan, date=date), market, member_bytes(market))


def write_tar(path, members):
    """A TAR at path (which must not exist) holding (name, bytes) pairs as regular files, in order."""
    with open(path, "xb") as handle:
        with tarfile.open(fileobj=handle, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for name, data in members:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mtime = TAR_MTIME
                info.mode = 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(data))
    return path


def build_archive(directory, members, *, name="data.tar"):
    """Write members (Member, or Market for its own path) as a TAR into directory; the Archive."""
    found = tuple(item if isinstance(item, Member) else member(item) for item in members)
    path = write_tar(os.path.join(directory, name), [(item.path, item.data) for item in found])
    return Archive(path, found)


def write_member_tree(directory, markets, *, plan=PLAN):
    """Each market's bz2 member at directory/<member path> (the raw/<sha>/ layout); the paths written."""
    written = []
    for market in markets:
        target = os.path.join(directory, *member_path(market, plan=plan).split("/"))
        os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
        with open(target, "xb") as handle:
            handle.write(member_bytes(market))
        written.append(target)
    return written


def standard_markets():
    return tuple(synthetic.generate(spec) for spec in STANDARD_SPECS)


def standard_archive(directory, *, name="data.tar"):
    """Four 2015-05 markets (see the module docstring)."""
    return build_archive(directory, standard_markets(), name=name)


def gated_markets():
    """(the 2015-05 market, one market per GATED_MONTHS, the content-gate market), all small."""
    def spec(seed, month):
        return synthetic.Spec(seed=seed, runners=5, pre_off_s=60, inplay_s=10, market_time="2015-05-09T16:20:00.000Z",
                              options=frozenset({"month:" + month}))

    kept = synthetic.generate(spec(201, STANDARD_MONTH))
    gated = tuple(synthetic.generate(spec(202 + i, month)) for i, month in enumerate(GATED_MONTHS))
    content = synthetic.generate(spec(209, GATED_MONTHS[0]))
    return kept, gated, content


def gated_archive(directory, *, name="gated.tar"):
    """The 2015-05 market, the four gated months at their own paths, and the 2026-01 market at a 2015-05 path."""
    kept, gated, content = gated_markets()
    members = [member(kept)] + [member(market) for market in gated]
    members.append(member(content, date=STANDARD_MONTH + "-09"))
    return build_archive(directory, members, name=name)
