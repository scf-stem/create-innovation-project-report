from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bootstrap_runtime import bootstrap  # noqa: E402
from check_skill_compatibility import check  # noqa: E402


class CompatibilityTest(unittest.TestCase):
    def test_bootstrap_requires_no_third_party_packages(self):
        result = bootstrap(SKILL_ROOT, check_only=True)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["core_is_standard_library_only"])
        self.assertEqual(result["third_party_modules"], [])

    def test_skill_has_no_local_collision_or_metadata_error(self):
        result = check(SKILL_ROOT, [SKILL_ROOT.parent], run_help=False)
        self.assertEqual(result["status"], "compatible", result["errors"])
        self.assertEqual(result["name_collisions"], [])

    def test_bootstrap_auto_installs_future_missing_module(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "feature.py").write_text("import imaginary_dependency\n", encoding="utf-8")
            with patch(
                "bootstrap_runtime.missing_modules",
                side_effect=[["imaginary_dependency"], []],
            ), patch(
                "bootstrap_runtime.install_missing",
                return_value=Path("/tmp/isolated-venv/bin/python"),
            ) as install:
                result = bootstrap(root, check_only=False)
            install.assert_called_once_with(["imaginary_dependency"])
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["installed_packages"], ["imaginary_dependency"])


if __name__ == "__main__":
    unittest.main()
