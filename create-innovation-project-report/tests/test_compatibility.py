from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bootstrap_runtime import bootstrap  # noqa: E402
from check_skill_compatibility import check, scan_skill_names  # noqa: E402


class CompatibilityTest(unittest.TestCase):
    def test_bootstrap_requires_no_third_party_packages(self):
        result = bootstrap(SKILL_ROOT, check_only=True)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["core_is_standard_library_only"])
        self.assertEqual(result["third_party_modules"], [])
        humanizer = result["skill_dependencies"]["humanizer-zh"]
        self.assertTrue(humanizer["usable"])
        self.assertIn(humanizer["mode"], {"bundled", "installed"})
        self.assertTrue(Path(humanizer["path"]).is_dir())

    def test_skill_has_no_local_collision_or_metadata_error(self):
        result = check(SKILL_ROOT, [SKILL_ROOT.parent], run_help=False)
        self.assertEqual(result["status"], "compatible", result["errors"])
        self.assertEqual(result["name_collisions"], [])

    def test_skill_scan_excludes_vendored_nested_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main-skill"
            nested = main / "vendor" / "nested-skill"
            sibling = root / "sibling-skill"
            nested.mkdir(parents=True)
            sibling.mkdir()
            (main / "SKILL.md").write_text(
                "---\nname: main-skill\ndescription: test\n---\n",
                encoding="utf-8",
            )
            (nested / "SKILL.md").write_text(
                "---\nname: nested-skill\ndescription: test\n---\n",
                encoding="utf-8",
            )
            (sibling / "SKILL.md").write_text(
                "---\nname: sibling-skill\ndescription: test\n---\n",
                encoding="utf-8",
            )

            names, scanned = scan_skill_names([root])

            self.assertEqual(scanned, 2)
            self.assertEqual(set(names), {"main-skill", "sibling-skill"})

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
            ) as install, patch(
                "bootstrap_runtime.provision_skill_dependencies",
                return_value={},
            ):
                result = bootstrap(root, check_only=False)
            install.assert_called_once_with(["imaginary_dependency"])
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["installed_packages"], ["imaginary_dependency"])

    def test_bootstrap_installs_bundled_humanizer_into_agent_skills_root(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_root = Path(temp) / "skills"
            result = bootstrap(
                SKILL_ROOT,
                check_only=False,
                agent_skills_root=skills_root,
            )

            humanizer = result["skill_dependencies"]["humanizer-zh"]
            installed = skills_root / "humanizer-zh"
            self.assertEqual(result["status"], "ready")
            self.assertEqual(humanizer["mode"], "installed")
            self.assertTrue(humanizer["installed_now"])
            self.assertEqual(Path(humanizer["path"]).resolve(), installed.resolve())
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue(
                (installed / ".managed-by-create-innovation-project-report").is_file()
            )

            second_result = bootstrap(
                SKILL_ROOT,
                check_only=False,
                agent_skills_root=skills_root,
            )
            second_humanizer = second_result["skill_dependencies"]["humanizer-zh"]
            self.assertEqual(second_humanizer["mode"], "installed")
            self.assertFalse(second_humanizer["installed_now"])

    def test_first_run_infers_sibling_agent_skills_root(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_root = Path(temp) / "skills"
            installed_skill = skills_root / "create-innovation-project-report"
            shutil.copytree(SKILL_ROOT, installed_skill)

            result = bootstrap(installed_skill, check_only=False)

            humanizer = result["skill_dependencies"]["humanizer-zh"]
            self.assertEqual(result["status"], "ready")
            self.assertEqual(humanizer["mode"], "installed")
            self.assertTrue(humanizer["installed_now"])
            self.assertTrue((skills_root / "humanizer-zh" / "SKILL.md").is_file())

    def test_bootstrap_check_only_does_not_install_skill_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_root = Path(temp) / "skills"
            result = bootstrap(
                SKILL_ROOT,
                check_only=True,
                agent_skills_root=skills_root,
            )

            humanizer = result["skill_dependencies"]["humanizer-zh"]
            self.assertEqual(humanizer["mode"], "bundled")
            self.assertTrue(humanizer["install_pending"])
            self.assertFalse((skills_root / "humanizer-zh").exists())

    def test_bootstrap_preserves_incompatible_existing_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_root = Path(temp) / "skills"
            existing = skills_root / "humanizer-zh"
            existing.mkdir(parents=True)
            incompatible = "---\nname: another-skill\ndescription: test\n---\n"
            (existing / "SKILL.md").write_text(incompatible, encoding="utf-8")

            result = bootstrap(
                SKILL_ROOT,
                check_only=False,
                agent_skills_root=skills_root,
            )

            humanizer = result["skill_dependencies"]["humanizer-zh"]
            self.assertEqual(result["status"], "ready")
            self.assertEqual(humanizer["mode"], "bundled")
            self.assertTrue(humanizer["warnings"])
            self.assertEqual(
                (existing / "SKILL.md").read_text(encoding="utf-8"),
                incompatible,
            )

    def test_bootstrap_uses_bundled_skill_when_installation_fails(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "bootstrap_runtime.install_bundled_skill",
            return_value=(False, "read-only target"),
        ):
            result = bootstrap(
                SKILL_ROOT,
                check_only=False,
                agent_skills_root=Path(temp) / "skills",
            )

            humanizer = result["skill_dependencies"]["humanizer-zh"]
            self.assertEqual(result["status"], "ready")
            self.assertEqual(humanizer["mode"], "bundled")
            self.assertIn("read-only target", humanizer["warnings"])


if __name__ == "__main__":
    unittest.main()
