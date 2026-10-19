"""One controller tab, end to end (DESIGN.md 9.2 item 8; Phase 0c): a second tab is read-only until it claims control.

One `bin/suite serve --port 0` child, synthetic only, under a temporary HOME; an unguarded client child plays two
tabs (two tokens from the control socket's new_code). The read-only tab still gets every frame; its commands get
409 not_controller; claim_control makes it the controller and the first tab read-only; the clock runs only while
the new controller watches (I-19), so a claim from a tab without a stream pauses it with not_watched. No client
script prints a code or a token. The UI side is ui/tests/control.test.mjs.
"""

import os
import re
import unittest

from betangel_suite.api import routes
from tests import ROOT
from tests import test_http_support as support


class ClaimControlTests(unittest.TestCase):

    def test_a_read_only_tab_watches_and_claims_control(self):
        home = support.short_home(self)
        serving, port = support.serve(self, home)
        results = support.client(self, home, port, r"""
first = bootstrap()
first_stream = Stream(first)
command(first, "open_market", {"seed": 12})
command(first, "set_speed", {"speed_x100": 1000})
results["first_play"] = command(first, "play")
first_stream.until(lambda item: item["t"] == "frame" and not item["clock"]["paused"])
second = bootstrap()
results["roles"] = [query(first)[1]["controller"], query(second)[1]["controller"]]
results["second_play"] = command(second, "pause")
second_stream = Stream(second)
seen = second_stream.until(lambda item: item["t"] == "frame" and not item["clock"]["paused"])
results["read_only_sees_frames"] = seen["t"] if isinstance(seen, dict) else seen
second_stream.close()                       # the read-only tab steps away, then claims without a stream
results["claim"] = command(second, "claim_control")
paused = first_stream.until(lambda item: item["t"] == "frame" and item["clock"]["paused"], timeout=5)
results["paused"] = paused["clock"]["pause_reason"]
results["roles_after"] = [query(first)[1]["controller"], query(second)[1]["controller"]]
results["first_play_after"] = command(first, "play")
results["second_play_unwatched"] = command(second, "play")
second_stream = Stream(second)
second_stream.next(5)
results["second_play_watched"] = command(second, "play")
moving = first_stream.until(lambda item: item["t"] == "frame" and not item["clock"]["paused"], timeout=5)
results["first_sees_play"] = moving["t"] if isinstance(moving, dict) else moving
results["claim_back"] = command(first, "claim_control")
results["second_after_claim_back"] = command(second, "pause")
results["claim_args"] = command(first, "claim_control", {"x": 1})
first_stream.close()
second_stream.close()
""")
        self.assertEqual(results["first_play"], [200, {"ok": True}])
        self.assertEqual(results["roles"], [True, False])
        self.assertEqual(results["second_play"], [409, {"ok": False, "code": "not_controller"}])
        self.assertEqual(results["read_only_sees_frames"], "frame")
        self.assertEqual(results["claim"], [200, {"ok": True}])
        self.assertEqual(results["paused"], "not_watched")             # the new controller is not watching
        self.assertEqual(results["roles_after"], [False, True])
        self.assertEqual(results["first_play_after"], [409, {"ok": False, "code": "not_controller"}])
        self.assertEqual(results["second_play_unwatched"], [200, {"ok": False, "code": "not_watched"}])
        self.assertEqual(results["second_play_watched"], [200, {"ok": True}])
        self.assertEqual(results["first_sees_play"], "frame")           # the read-only tab watches the replay
        self.assertEqual(results["claim_back"], [200, {"ok": True}])
        self.assertEqual(results["second_after_claim_back"], [409, {"ok": False, "code": "not_controller"}])
        self.assertEqual(results["claim_args"], [400, {"ok": False, "code": "bad_args"}])
        self.assertEqual(serving.terminate(), 0)
        for line in serving.stderr().splitlines():
            self.assertRegex(line, r"\Ahttp:[0-9]{3}:[a-z_]+\Z")
        self.assertEqual(support.secret_shaped(serving.stdout() + serving.stderr()), [])

    def test_the_ui_knows_the_query_enum_and_claim_control(self):
        with open(os.path.join(ROOT, "ui", "stream.js"), encoding="utf-8") as handle:
            source = handle.read()
        queries = re.findall(r"'([a-z_]+)'", re.search(r"QUERIES = Object\.freeze\(\[([^\]]*)\]", source).group(1))
        self.assertEqual(tuple(queries), routes.QUERIES)
        self.assertIn("claim_control", routes.IMPLEMENTED)
        with open(os.path.join(ROOT, "ui", "app.js"), encoding="utf-8") as handle:
            app = handle.read()
        self.assertIn("api.command('claim_control', {})", app)
        self.assertIn("api.query('session')", app)


if __name__ == "__main__":
    unittest.main()
