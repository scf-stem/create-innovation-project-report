from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from report_config import AGENTS, DOMAINS, MODES, load_config, output_path
from plan_report import build_plan
from bootstrap_runtime import bootstrap, cache_root, install_missing, stdlib_module_names
from check_skill_compatibility import check, run_help_checks
from inventory_project import build_inventory
from inspect_experiment_data import inspect
from appendix_images import insert_appendix
from audit_docx import audit, toc_status
from test_appendix_images import create_minimal_docx, png_bytes, W_NS


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "任务 配置.json"
        self.project = self.root / "项目 空格"
        self.project.mkdir()
        self.previous = self.root / "previous.docx"
        create_minimal_docx(self.previous, "Existing report")

    def tearDown(self):
        self.temp.cleanup()

    def load(self, extra=None):
        value = {"project": {"name": "项目 A", "root": "项目 空格"}, "output": {"date": "2026-09-20"}}
        if extra:
            for key, fields in extra.items():
                if isinstance(fields, dict) and isinstance(value.get(key), dict):
                    value[key].update(fields)
                else:
                    value[key] = fields
        self.config.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8-sig")
        return load_config(self.config)

    def test_paths_do_not_depend_on_callers_working_directory(self):
        cfg = self.load()
        self.assertEqual(cfg["project"]["root"], str(self.project.resolve()))
        self.assertEqual(output_path(cfg), self.project.resolve() / "output/doc/项目 A_综合实践报告_20260920.docx")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/plan_report.py"), "--config", str(self.config)], cwd=self.root.parent, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["target"], str(output_path(cfg)))
        self.assertFalse((self.project / "output").exists())

    def test_agent_domain_mode_matrix_preserves_user_choices(self):
        for agent in AGENTS:
            for domain in DOMAINS:
                for mode in MODES:
                    with self.subTest(agent=agent, domain=domain, mode=mode):
                        cfg = self.load({"project": {"domain": domain}, "runtime": {"agent": agent}, "task": {"mode": mode, "previous": "previous.docx"}})
                        plan = build_plan(cfg)
                        self.assertEqual(plan["status"], "planned")
                        self.assertEqual(plan["config"]["project"]["domain"], domain)
                        if mode == "audit":
                            self.assertIsNone(plan["target"])
                            self.assertNotIn("document", [step["id"] for step in plan["modules"]])
                        if mode == "outline":
                            self.assertEqual(plan["effective_format"], "markdown")
                            self.assertEqual([step["id"] for step in plan["modules"]], ["inventory", "outline"])

    def test_format_and_language_routing(self):
        cfg = self.load({"output": {"format": "markdown", "report_label": "Project Report", "version": "v2.1"}, "task": {"language": "en"}})
        plan = build_plan(cfg)
        self.assertTrue(plan["target"].endswith("项目 A_Project Report_v2.1.md"))
        by_id = {step["id"]: step for step in plan["modules"]}
        self.assertEqual(by_id["render"]["status"], "not-applicable")
        self.assertIsNone(by_id["audit"]["script"])
        self.assertIsNone(by_id["appendix"]["script"])
        self.assertNotIn("humanizer", by_id["polish"]["reference"])

    def test_missing_renderer_required_vs_preferred(self):
        cfg = self.load({"runtime": {"capabilities": {"renderer": False}}})
        self.assertEqual(build_plan(cfg)["status"], "planned")
        self.assertTrue(build_plan(cfg)["warnings"])
        cfg["quality"]["render"] = "required"
        self.assertEqual(build_plan(cfg)["status"], "blocked")
        cfg["quality"]["render"] = "skip"
        self.assertEqual(build_plan(cfg)["status"], "planned")

    def test_writer_missing_does_not_silently_change_format(self):
        cfg = self.load({"output": {"format": "pdf"}, "runtime": {"capabilities": {"document_writer": False}}})
        plan = build_plan(cfg)
        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(plan["effective_format"], "pdf")

    def test_existing_file_is_preserved(self):
        cfg = self.load({"output": {"directory": "."}})
        target = output_path(cfg)
        target.write_bytes(b"user content")
        self.assertEqual(build_plan(cfg)["status"], "blocked")
        self.assertEqual(target.read_bytes(), b"user content")

    def test_bad_fields_dates_paths_and_types_fail(self):
        cases = [
            {"schema_version": 2}, {"schema_version": True}, {"output": {"date": "2026-02-30"}},
            {"project": {"name": "../oops"}}, {"project": {"name": "CON"}},
            {"project": {"root": "missing"}}, {"task": {"mode": "audit"}},
            {"task": {"mode": "revise", "previous": "missing.docx"}},
            {"output": {"versoin": "v1.0"}}, {"document": {"toc": "false"}},
            {"modules": {"polish": "false"}}, {"quality": {"max_pages_without_visual": 0}},
            {"runtime": {"capabilities": {"renderer": "yes"}}}, {"extensions": []},
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load(value)

    def test_cli_override_and_extension_passthrough(self):
        self.load({"extensions": {"team": {"template": "company.docx"}}})
        cfg = load_config(self.config, {"task": {"mode": "outline"}})
        self.assertEqual(cfg["task"]["mode"], "outline")
        self.assertEqual(build_plan(cfg)["extensions"], {"team": {"template": "company.docx"}})

    def test_conversion_audits_source_and_target_formats(self):
        cfg = self.load({"task": {"mode": "revise", "previous": "previous.docx"}, "output": {"format": "markdown"}})
        checks = [step for step in build_plan(cfg)["modules"] if step["id"] == "audit"]
        self.assertEqual([step["format"] for step in checks], ["docx", "markdown"])
        self.assertEqual(checks[0]["script"], "audit_docx.py")
        self.assertIsNone(checks[1]["script"])

    def test_cli_uses_utf8_in_non_utf8_environment(self):
        env = dict(os.environ, PYTHONIOENCODING="ascii")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/plan_report.py"), "--template"], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(json.loads(result.stdout.decode("utf-8"))["project"]["name"], "项目名称")


class RuntimeTest(unittest.TestCase):
    def test_default_is_read_only_and_offline_never_installs_packages(self):
        with tempfile.TemporaryDirectory() as temp, patch("bootstrap_runtime.install_missing") as install:
            target = Path(temp) / "skills"
            result = bootstrap(ROOT, agent_skills_root=target)
            self.assertEqual(result["status"], "ready")
            self.assertFalse(target.exists())
            with patch("bootstrap_runtime.missing_modules", return_value=["docx"]):
                result = bootstrap(ROOT, check_only=False, offline=True, agent_skills_root=None)
                self.assertEqual(result["status"], "dependencies-missing")
            install.assert_not_called()

    def test_unknown_packages_not_guessed(self):
        with patch("bootstrap_runtime.cache_root", return_value=Path(tempfile.gettempdir()) / "unused-report-test"), patch("bootstrap_runtime.venv.EnvBuilder") as builder:
            # Validation must precede creating any installation directories.
            with self.assertRaisesRegex(ValueError, "approved package mapping"):
                install_missing(["untrusted_unknown_package"])
            builder.assert_not_called()

    def test_python39_windows_dynamic_stdlib_is_recognized(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Lib").mkdir()
            (root / "DLLs").mkdir()
            (root / "DLLs/math.pyd").touch()
            (root / "DLLs/zlib.pyd").touch()
            with patch("bootstrap_runtime.sys.stdlib_module_names", (), create=True), patch("bootstrap_runtime.sys.base_prefix", str(root)), patch("bootstrap_runtime.sys.prefix", str(root)), patch("bootstrap_runtime.sysconfig.get_paths", return_value={"stdlib": str(root / "Lib")}), patch("bootstrap_runtime.sysconfig.get_config_var", return_value=None):
                self.assertTrue({"math", "zlib"}.issubset(stdlib_module_names()))

    def test_cache_override_and_platform_defaults(self):
        fixture_home = Path(tempfile.gettempdir()) / "report-cache-home"
        for system, expected in (("win32", "AppData"), ("darwin", "Caches"), ("linux", ".cache")):
            with patch.dict(os.environ, {}, clear=True), patch("bootstrap_runtime.sys.platform", system), patch("bootstrap_runtime.Path.home", return_value=fixture_home):
                self.assertIn(expected, str(cache_root()))
        with patch.dict(os.environ, {"REPORT_SKILL_CACHE": tempfile.gettempdir()}):
            self.assertEqual(cache_root(), Path(tempfile.gettempdir()).resolve())

    def test_missing_optional_metadata_and_other_copies_do_not_block(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            one = parent / "one" / ROOT.name
            two = parent / "two" / ROOT.name
            shutil.copytree(ROOT, one, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT, two, ignore=shutil.ignore_patterns("__pycache__"))
            (one / "agents/openai.yaml").unlink()
            result = check(one, [parent], run_help=False)
            self.assertEqual(result["status"], "compatible", result["errors"])
            self.assertEqual(len(result["name_collisions"]), 1)
            self.assertTrue(result["warnings"])

    def test_bad_script_returns_structured_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / ROOT.name
            shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns("__pycache__"))
            (target / "scripts/broken.py").write_text("def broken(:", encoding="utf-8")
            result = check(target, [], run_help=False)
            self.assertEqual(result["status"], "incompatible")
            self.assertIn("broken.py", str(result["errors"]))

    def test_help_timeout_is_reported(self):
        with patch("check_skill_compatibility.subprocess.run", side_effect=subprocess.TimeoutExpired("test", 15)):
            self.assertTrue(run_help_checks(ROOT))


class DataAndInventoryTest(unittest.TestCase):
    def test_locale_data_and_row_width(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "测量.csv"
            path.write_text("x;y\n1,5;2\n2,5\n", encoding="utf-8-sig")
            result = inspect(path, "utf-8-sig", ";", 100, ",", "")
            self.assertEqual(result["columns"][0]["numeric"]["mean"], 2)
            self.assertEqual(result["row_width_issues"], 1)
            self.assertEqual(result["columns"][1]["missing_count"], 1)
            result = inspect(path, "utf-8-sig", ";", 1, ",", "")
            self.assertTrue(result["truncated"])

    def test_duplicate_headers_fail_without_losing_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "data.csv"
            path.write_text("x, x\n1,2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique"):
                inspect(path, "utf-8", ",", 100)

    def test_pruned_directories_and_modern_software_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "node_modules").mkdir()
            (root / "node_modules/ignored.js").write_text("ignore", encoding="utf-8")
            (root / "app.tsx").write_text("app", encoding="utf-8")
            (root / "custom").mkdir()
            (root / "custom/file.md").write_text("ignore", encoding="utf-8")
            result = build_inventory(root, False, True, False, exclude_dirs=["custom"])
            self.assertEqual(result["file_count"], 1)
            self.assertEqual(result["files"][0]["type"], "源码")


class DocxPortabilityTest(unittest.TestCase):
    def test_english_appendix_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, manifest = root / "source.docx", root / "output.docx", root / "images.json"
            create_minimal_docx(source, "See Appendix Figure A-1.")
            (root / "photo.png").write_bytes(png_bytes())
            manifest.write_text(json.dumps({"appendix_title": "Appendix A Project Images", "caption_prefix": "Appendix Figure", "description_prefix": "Note: ", "images": [{"path": "photo.png", "number": "A-1", "caption": "Assembly", "description": "Visible parts"}]}), encoding="utf-8")
            insert_appendix(source, output, manifest)
            result = audit(output, [], [], check_cross_references=True)
            self.assertEqual(result["cross_references"]["missing_targets"], [])
            self.assertIn("Appendix FigureA-1", result["cross_references"]["caption_targets"])
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                insert_appendix(source, output, manifest)
            self.assertEqual(output.read_bytes(), original)

    def test_toc_requires_complete_own_field(self):
        fixtures = [
            ('<w:instrText>TOC \\o "1-3"</w:instrText>', False),
            ('<w:fldChar w:fldCharType="begin"/><w:instrText>TOC </w:instrText><w:fldChar w:fldCharType="end"/>', False),
            ('<w:fldChar w:fldCharType="begin"/><w:instrText>TO</w:instrText><w:instrText>C </w:instrText><w:fldChar w:fldCharType="separate"/><w:fldChar w:fldCharType="end"/>', True),
            ('<w:fldSimple w:instr="TOC"/>', True),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "doc.docx"
            for field, expected in fixtures:
                with self.subTest(field=field):
                    with zipfile.ZipFile(path, "w") as archive:
                        archive.writestr("word/document.xml", f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r>{field}</w:r></w:p></w:body></w:document>')
                    self.assertEqual(toc_status(path)["valid"], expected)


if __name__ == "__main__":
    unittest.main()
