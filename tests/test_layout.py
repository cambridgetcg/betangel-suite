"""Repository layout rules (DESIGN.md 3.4, 3.6)."""

import os
import unittest

from tests import ROOT


class LayoutTests(unittest.TestCase):

    def test_no_top_level_python_file(self):
        # `unittest discover -t .` and bin/_launch.py put the checkout root on sys.path, where a stray
        # json.py or betangel_research.py would shadow the real module.
        found = [name for name in os.listdir(ROOT) if name.endswith((".py", ".pyc", ".pth", ".so"))
                 or name in ("betangel_research", "__pycache__")]
        self.assertEqual(found, [])

    def test_no_bytecode_caches_in_the_checkout(self):
        # Every run uses -B; a stale .pyc beside a .py would still be loaded, so none may exist.
        found = [os.path.relpath(directory, ROOT) for directory, dirs, _files in os.walk(ROOT)
                 if "__pycache__" in dirs and ".git" not in os.path.relpath(directory, ROOT).split(os.sep)]
        self.assertEqual(found, [])

    def test_launcher_is_an_executable_posix_sh_script(self):
        path = os.path.join(ROOT, "bin", "suite")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.readline(), "#!/bin/sh\n")
        self.assertTrue(os.access(path, os.X_OK))

    def test_phase_0a_runtime_modules_exist(self):
        present = set(os.listdir(os.path.join(ROOT, "betangel_suite")))
        for name in ("__init__.py", "guard.py", "pin.py", "rx.py", "errors.py", "roots.py", "runmarker.py",
                     "config.py", "cli.py"):
            self.assertIn(name, present)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "pin", "betangel-research.json")))


if __name__ == "__main__":
    unittest.main()
