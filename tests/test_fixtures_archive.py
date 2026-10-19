"""Synthetic TARs through the vendored ingest and index (DESIGN.md 4.2, 5.2, 11; invariant I-11).

tests/fixtures/gen.py writes synthetic members in the documented layout (PRO/YYYY/Mon/D/<eventId>/<marketId>.bz2)
into a TAR under TMPDIR. Upstream's own archive.ingest_archive and market_index.index_archive, test-only oracles
imported here and nowhere outside tests/ (AGENTS.md rule 2; tests/test_imports.py scans only the package, bin/
and tools/, and checks that rx exports neither), ingest and index it into a temporary data root. The index must
see every synthetic market with the facts the generator put there, and the month gate must refuse the 2026 and
2027 members (by path, never decompressed) and a member whose content names 2026-01 under a 2015-05 path. A member
whose "marketTime" keys are escaped passes ingest's byte scan and is stored; the index refuses its market at index
time, and head.files[] still lists the member as indexed.
"""

import bz2
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from betangel_research.betfair.backtest import archive as upstream_archive        # test-only oracle (4.2)
from betangel_research.betfair.backtest import market_index as upstream_index     # test-only oracle (4.2)

from betangel_suite import rx, synthetic
from tests import rmtree
from tests.fixtures import gen


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class ArchiveCase(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="fixtures-archive-")
        self.addCleanup(rmtree, self.base)
        self.tars = os.path.join(self.base, "tars")
        self.data_root = os.path.join(self.base, "root")
        os.mkdir(self.tars, 0o700)
        os.mkdir(self.data_root, 0o700)
        self.root, problems = upstream_archive.check_data_root(self.data_root)
        self.assertEqual(problems, [])

    def ingest(self, archive):
        return upstream_archive.ingest_archive(archive.path, self.data_root)

    def raw(self, archive_sha, member_path):
        return os.path.join(self.data_root, "raw", archive_sha, *member_path.split("/"))


class StandardArchiveTests(ArchiveCase):

    def test_ingest_and_index_see_every_synthetic_market(self):
        archive = gen.standard_archive(self.tars)
        markets = {item.market.market_id: item.market for item in archive.members}
        self.assertEqual(len(markets), len(gen.STANDARD_SPECS))
        result = self.ingest(archive)
        self.assertEqual(result["status"], "ingested", result)
        sha = result["archive_sha256"]
        self.assertEqual(sha, sha256(Path(archive.path).read_bytes()))
        self.assertEqual((result["plan"], result["months"], result["members"], result["written"], result["refused"]),
                         ("PRO", [gen.STANDARD_MONTH], len(markets), len(markets), 0))
        self.assertEqual(result["sealed_holdout_members"], 0)

        manifest, _manifest_sha = upstream_index.load_manifest(self.root, sha)
        self.assertEqual([m["path"] for m in manifest["members"]], sorted(item.path for item in archive.members))
        for entry in manifest["members"]:
            item = next(member for member in archive.members if member.path == entry["path"])
            self.assertEqual((entry["plan"], entry["month"], entry["file_type"], entry["market_id"], entry["event_id"]),
                             ("PRO", gen.STANDARD_MONTH, "market", item.market.market_id, item.market.event_id))
            self.assertEqual((entry["sha256"], entry["size_bytes"]), (sha256(item.data), len(item.data)))
            self.assertEqual(entry["decompressed_bytes"], len(gen.member_text(item.market)))
            self.assertEqual(entry["content_months"], [] if item.market.market_time is None else [gen.STANDARD_MONTH])
            with open(self.raw(sha, entry["path"]), "rb") as handle:
                self.assertEqual(handle.read(), item.data)              # stored as is, never decompressed

        summary = upstream_index.index_archive(self.root, sha)
        self.assertEqual((summary["markets"], summary["files_indexed"], summary["files_unreadable"],
                          summary["files_refused"], summary["markets_refused"], summary["state"]),
                         (len(markets), len(markets), 0, 0, 0, "written"))
        index = os.path.join(self.data_root, "index", sha)
        with open(os.path.join(index, upstream_index.HEAD_FILE), "rb") as handle:
            head = upstream_index.loads_strict(handle.read())
        self.assertEqual(head["kind"], "betfair_historical_market_index_head")
        self.assertEqual(sorted((f["status"], tuple(f["markets"])) for f in head["files"]),
                         sorted(("indexed", (market_id,)) for market_id in markets))
        with open(os.path.join(index, upstream_index.MARKETS_FILE), "rb") as handle:
            records = [upstream_index.loads_strict(line) for line in handle]
        self.assertEqual(sorted(record["market_id"] for record in records), sorted(markets))
        for record in records:
            self.check_record(record, markets[record["market_id"]])
        # Indexing again is a no-op over the same bytes.
        self.assertEqual(upstream_index.index_archive(self.root, sha)["state"], "unchanged")
        self.assertEqual(self.ingest(archive)["status"], "already_ingested")

    def check_record(self, record, market):
        checks, decision, outcome = record["checks"], record["decision_time"], record["evaluator_only_outcome"]
        published = market.market_time is not None
        self.assertEqual(checks["event_id_mismatch"], False)
        self.assertEqual(checks["month_mismatch"], False if published else None)
        self.assertEqual(checks["date_mismatch"], False if published else None)
        self.assertEqual(checks["unrecognised_runner_statuses"], [])
        # Every definition key is one market_index tracks, except the ladder type validate's V9 needs.
        self.assertEqual(checks["untracked_definition_fields"], ["priceLadderDefinition"])
        self.assertTrue(outcome["read_complete"])
        self.assertEqual((outcome["final_status"], outcome["closed_reached"], outcome["winners_observed"]),
                         ("CLOSED", True, 1))
        self.assertEqual(outcome["closed_first_pt"], market.close_pt)
        self.assertEqual(outcome["settled_time"], synthetic.iso_ms(market.close_pt))
        finals = {runner["id"]: runner for runner in outcome["final_runners"]}
        self.assertEqual(set(finals), set(market.selection_ids))
        self.assertEqual([rid for rid, runner in finals.items() if runner["status"] == "WINNER"], [market.winner_id])
        self.assertEqual(outcome["missing_final_bsp_runner_ids"], [])
        self.assertEqual(outcome["unusable_final_bsp_runner_ids"], [])
        self.assertEqual(outcome["dead_heat"], False)
        if not published:
            self.assertEqual(decision, upstream_index.no_view())       # no marketTime: no decision-time view
            self.assertEqual(outcome["market_time_months"], [])
            return
        self.assertEqual(decision["first_published_market_time"], {"pt": market.start_pt, "value": market.market_time})
        self.assertEqual(decision["view_ends"], {"pt": market.off_pt, "reason": "first_published_scheduled_off"})
        self.assertEqual([runner["id"] for runner in decision["runners"]], sorted(market.selection_ids))
        self.assertEqual(outcome["market_time_months"], [gen.STANDARD_MONTH])
        removals = [(item["id"], item["status"], item["removal_date"]) for item in decision["removals"]]
        if market.removed_ids:
            self.assertEqual(removals, [(market.removed_ids[0], "REMOVED", synthetic.iso_ms(market.plan.removal[0]))])
        else:
            self.assertEqual(removals, [])


class MonthGateTests(ArchiveCase):

    def test_gated_months_are_refused_and_never_stored(self):
        archive = gen.gated_archive(self.tars)
        kept, gated, content = gen.gated_markets()
        result = self.ingest(archive)
        self.assertEqual(result["status"], "ingested", result)
        sha = result["archive_sha256"]
        expected = {month: upstream_archive.month_gate(month) for month in gen.GATED_MONTHS}
        self.assertEqual(expected, {"2026-01": "month_sealed_holdout", "2026-09": "month_exposed_exploratory_only",
                                    "2026-10": "month_not_prospective", "2027-01": "month_prospective_out_of_scope"})
        reasons = {}
        for reason in list(expected.values()) + ["content_" + expected["2026-01"]]:
            reasons[reason] = reasons.get(reason, 0) + 1
        self.assertEqual((result["members"], result["refused"], result["month_unknown_members"]),
                         (1, len(gen.GATED_MONTHS) + 1, 0))
        self.assertEqual(result["refused_by_reason"], dict(sorted(reasons.items())))
        self.assertEqual(result["sealed_holdout_members"], 2)           # 2026-01 by path and by content

        manifest, _sha = upstream_index.load_manifest(self.root, sha)
        self.assertEqual([m["market_id"] for m in manifest["members"]], [kept.market_id])
        refused = {item["path"]: item for item in manifest["refused"]}
        for market in gated:
            item = refused[gen.member_path(market)]
            self.assertEqual((item["month"], item["reason"], item["content_months"]),
                             (market.month, expected[market.month], None))   # refused by path: never decompressed
        item = refused[gen.member_path(content, date=gen.STANDARD_MONTH + "-09")]
        self.assertEqual((item["month"], item["reason"], item["content_months"]),
                         (gen.STANDARD_MONTH, "content_month_sealed_holdout", ["2026-01"]))
        for path in refused:
            self.assertFalse(os.path.lexists(self.raw(sha, path)))
        self.assertEqual(os.listdir(os.path.join(self.data_root, "raw", sha, "PRO")), ["2015"])

        summary = upstream_index.index_archive(self.root, sha)
        self.assertEqual((summary["markets"], summary["files"], summary["markets_refused"]), (1, 1, 0))

    def test_an_escaped_market_time_passes_ingest_and_the_index_refuses_its_market(self):
        # Nuance's PR #4 review, item 8. ingest's content scan reads only unescaped "marketTime" keys (archive.py:48-51),
        # so a 2026-01 market under a 2015-05 path, its keys escaped, is stored. market_index's parsed check refuses
        # the market, yet head.files[] still lists its member as indexed (market_index.py:739-741). Both are pinned
        # here before Phase 1a catalogue code is written against them.
        archive = gen.escaped_archive(self.tars)
        kept, escaped = gen.escaped_markets()
        path = gen.member_path(escaped, date=gen.STANDARD_MONTH + "-09")
        text = bz2.decompress(archive.members[1].data)
        self.assertEqual((archive.members[1].path, text.count(b'"marketTime"')), (path, 0))
        self.assertGreater(text.count(b'"market\\u0054ime":"2026-01-'), 0)
        self.assertEqual(json.loads(text.split(b"\n")[0])["mc"][0]["marketDefinition"]["marketTime"][:7], "2026-01")

        result = self.ingest(archive)
        self.assertEqual((result["status"], result["members"], result["refused"], result["sealed_holdout_members"]),
                         ("ingested", 2, 0, 0))
        sha = result["archive_sha256"]
        manifest, _sha = upstream_index.load_manifest(self.root, sha)
        entry = next(item for item in manifest["members"] if item["path"] == path)
        self.assertEqual((entry["month"], entry["market_id"], entry["content_months"]),
                         (gen.STANDARD_MONTH, escaped.market_id, []))          # the scan saw no marketTime
        with open(self.raw(sha, path), "rb") as handle:
            self.assertEqual(handle.read(), archive.members[1].data)          # stored

        summary = upstream_index.index_archive(self.root, sha)
        self.assertEqual((summary["markets"], summary["markets_refused"], summary["files"], summary["files_indexed"],
                          summary["files_refused"]), (1, 1, 2, 2, 0))
        index = os.path.join(self.data_root, "index", sha)
        with open(os.path.join(index, upstream_index.HEAD_FILE), "rb") as handle:
            head = upstream_index.loads_strict(handle.read())
        files = {item["path"]: item for item in head["files"]}
        self.assertEqual((files[path]["status"], files[path]["markets"]), ("indexed", [escaped.market_id]))
        self.assertEqual(head["refused_markets"], [{"market_id": escaped.market_id, "member_path": path,
                                                    "reason": "market_time_month_sealed_holdout"}])
        with open(os.path.join(index, upstream_index.MARKETS_FILE), "rb") as handle:
            records = [upstream_index.loads_strict(line) for line in handle]
        self.assertEqual([record["market_id"] for record in records], [kept.market_id])

    def test_an_archive_of_gated_months_only_is_refused_whole(self):
        _kept, gated, _content = gen.gated_markets()
        archive = gen.build_archive(self.tars, gated, name="only-gated.tar")
        result = self.ingest(archive)
        self.assertEqual((result["status"], result["problems"]), ("refused", ["archive:nothing_kept"]))
        self.assertEqual(result["refused"], len(gated))
        self.assertEqual(os.listdir(self.data_root), [])                 # nothing written at all


class LayoutTests(ArchiveCase):

    def test_member_path_is_the_documented_layout(self):
        for market in gen.standard_markets() + gen.gated_markets()[1]:
            path = gen.member_path(market)
            parsed, reason = rx.archive.parse_member_path(path)
            self.assertIsNone(reason)
            day = synthetic.iso_ms(market.market_time_ms)[:10]
            self.assertEqual(parsed, {"plan": "PRO", "month": market.month, "date": day, "event_id": market.event_id,
                                      "file_type": "market", "market_id": market.market_id})
            self.assertEqual(path.split("/")[3], str(int(day[8:])))     # the day without a leading zero
            self.assertIsNone(upstream_archive.name_problem(path))

    def test_archives_are_byte_for_byte_deterministic(self):
        first = gen.build_archive(self.tars, gen.gated_markets()[1], name="one.tar")
        second = gen.build_archive(self.tars, gen.gated_markets()[1], name="two.tar")
        self.assertEqual(Path(first.path).read_bytes(), Path(second.path).read_bytes())

    def test_member_tree_holds_the_bz2_streams(self):
        markets = gen.standard_markets()[:2]
        tree = os.path.join(self.base, "tree")
        written = gen.write_member_tree(tree, markets)
        self.assertEqual(written, [os.path.join(tree, *gen.member_path(m).split("/")) for m in markets])
        for path, market in zip(written, markets):
            with open(path, "rb") as handle:
                lines = bz2.decompress(handle.read()).split(b"\n")
            self.assertEqual(lines[-1], b"")
            self.assertEqual(lines[:-1], list(market.lines()))
            self.assertEqual(json.loads(lines[0])["mc"][0]["id"], market.market_id)


if __name__ == "__main__":
    unittest.main()
