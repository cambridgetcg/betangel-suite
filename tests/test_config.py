"""Suite config (DESIGN.md 3.8): the defaults table and strict loading of config.json."""

import json
import os
import unittest

from betangel_suite import config, roots, rx
from betangel_suite.errors import SuiteError
from tests import make_home, run_python


class DefaultsTests(unittest.TestCase):

    def test_defaults_are_the_section_3_8_table_with_yus_rulings(self):
        self.assertEqual(config.DEFAULTS, {
            "data_roots": [], "state_root": "~/betangel-data/suite.noindex", "port": 8765, "frame_hz": 10,
            "cap_profile": "v1-live-mirror", "commission_source": "user_package_unverified",
            "research_months_ruling": None, "run_marker": "~/.local/state/lab-runs/ACTIVE", "watch_grace_s": 600,
        })

    def test_commission_labels_are_upstream_labels(self):
        self.assertLessEqual(set(config.COMMISSION_SOURCES), set(rx.constants.COMMISSION_SOURCES))


class LoadTests(unittest.TestCase):

    def setUp(self):
        self.home = make_home(self)
        self.path = roots.config_path(self.home)

    def write(self, data, mode=0o600):
        with open(self.path, "wb") as handle:
            handle.write(data if isinstance(data, bytes) else json.dumps(data).encode())
        os.chmod(self.path, mode)

    def refused(self, code):
        with self.assertRaises(SuiteError) as caught:
            config.load(self.home)
        self.assertEqual(str(caught.exception), code)

    def test_missing_file_gives_a_copy_of_the_defaults(self):
        loaded = config.load(self.home)
        self.assertEqual(loaded, config.DEFAULTS)
        loaded["data_roots"].append("/x")
        self.assertEqual(config.DEFAULTS["data_roots"], [])

    def test_valid_overrides(self):
        values = {"port": 8766, "frame_hz": 5, "cap_profile": "practice", "watch_grace_s": 60,
                  "run_marker": "~/.local/state/lab-runs/ACTIVE", "research_months_ruling": None,
                  "commission_source": "user_package_verified", "data_roots": ["~/betangel-data/historic-pro"]}
        self.write(values)
        loaded = config.load(self.home)
        for key, value in values.items():
            self.assertEqual(loaded[key], value)
        self.assertEqual(config.expand(loaded["run_marker"], self.home),
                         os.path.join(self.home, ".local", "state", "lab-runs", "ACTIVE"))

    def test_invalid_values_are_refused_without_echoing_them(self):
        for key, value in (("port", "8765"), ("port", True), ("port", 80), ("frame_hz", 21), ("frame_hz", 10.0),
                           ("state_root", "~/elsewhere"), ("cap_profile", "unlimited"), ("commission_source", "made_up"),
                           ("run_marker", "~/betangel-data/ACTIVE"), ("run_marker", "~/BETANGEL-DATA/x"),
                           ("run_marker", "relative/ACTIVE"), ("run_marker", "~/"), ("run_marker", "~/runs/ACTIVE"),
                           ("run_marker", "~/decoy-never-created/ACTIVE"), ("run_marker", "/Users/x/.local/state/lab-runs/ACTIVE"),
                           ("data_roots", "~/x"),
                           ("data_roots", ["~/x", "~/x"]), ("data_roots", ["relative"]), ("watch_grace_s", 0),
                           ("research_months_ruling", "has space"), ("research_months_ruling", 7)):
            self.write({key: value})
            self.refused("config_invalid_value")

    def test_research_months_stay_hidden_until_a_reviewed_pr_lists_a_ruling(self):
        # Nuance's PR #2 review, item 12: any well-formed id used to load, so one config edit could put research-month
        # rows in the catalogue (DESIGN.md 5.3, 14). Only null loads until Yu rules on Q-Y7 and a reviewed PR lists the id.
        self.assertEqual(config.ACCEPTED_RULINGS, frozenset())
        for value in ("ruling-2026-01", "x", "", "null", "RULING-2026-01"):
            self.write({"research_months_ruling": value})
            self.refused("config_invalid_value")
        self.write({"research_months_ruling": None})
        self.assertIsNone(config.load(self.home)["research_months_ruling"])

    def test_shape_refusals(self):
        cases = ((b'{"port": 8765, "port": 8766}', "config_not_json"), (b'{"frame_hz": NaN}', "config_not_json"),
                 (b"{", "config_not_json"), (b"\xff\xfe", "config_not_json"), (b"[]", "config_not_object"),
                 (b'{"guard": false}', "config_unknown_key"), (b" " * (config.MAX_CONFIG_BYTES + 1), "config_too_large"))
        for data, code in cases:
            self.write(data)
            self.refused(code)

    def test_a_fifo_or_directory_at_config_json_is_refused_at_once(self):
        # Nuance's PR #2 review, item 22: a blocking open of a FIFO waits for a writer for ever. Each load runs in a
        # child with a timeout, so a regression fails here instead of hanging the whole run.
        for label, make in (("fifo", os.mkfifo), ("directory", os.mkdir)):
            home = make_home(self)
            make(roots.config_path(home))
            code = ("from betangel_suite import config\nfrom betangel_suite.errors import SuiteError\n"
                    "try:\n    config.load(%r)\nexcept SuiteError as exc:\n    print(exc.code)\n") % home
            result = run_python(code, home, timeout=20)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "config_insecure\n", ""), label)

    def test_file_safety(self):
        self.write({"port": 8765}, mode=0o620)
        self.refused("config_insecure")
        os.remove(self.path)
        target = os.path.join(self.home, "elsewhere.json")
        with open(target, "w") as handle:
            json.dump({"port": 8765}, handle)
        os.symlink(target, self.path)
        self.refused("config_unreadable")


if __name__ == "__main__":
    unittest.main()
