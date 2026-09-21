from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from audit_docx import audit, self_containment_status  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NAMESPACES = f'xmlns:w="{W}" xmlns:r="{R}" xmlns:a="{A}" xmlns:v="urn:schemas-microsoft-com:vml"'


def paragraph(value: str) -> str:
    element = ET.Element(f"{{{W}}}p")
    ET.SubElement(ET.SubElement(element, f"{{{W}}}r"), f"{{{W}}}t").text = value
    return ET.tostring(element, encoding="unicode")


def drawing(rid: str = "img", attribute: str = "embed") -> str:
    return f'<w:p><w:r><w:drawing><a:blip r:{attribute}="{rid}"/></w:drawing></w:r></w:p>'


def relationships(*items: dict) -> str:
    root = ET.Element(f"{{{PKG}}}Relationships")
    for item in items:
        ET.SubElement(root, f"{{{PKG}}}Relationship", {"Type": R + "/image", **item})
    return ET.tostring(root, encoding="unicode")


def fixture(path: Path, body: str = "", rels: str | None = None, extra: dict | None = None) -> None:
    # Minimal OOXML audit fixtures; no Office application is needed.
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document {NAMESPACES}><w:body>{body}</w:body></w:document>')
        if rels is not None:
            archive.writestr("word/_rels/document.xml.rels", rels)
        for name, value in (extra or {}).items():
            archive.writestr(name, value)


class SelfContainmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "报告 with spaces.docx"

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts/audit_docx.py"), str(self.path), "--json", *args],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )

    def test_embedded_images_resolve_encoded_and_root_relative_paths_without_mutation(self):
        fixture(
            self.path, drawing() + drawing("root"),
            relationships(
                {"Id": "img", "Target": "media/%E5%9B%BE%201.png"},
                {"Id": "root", "Target": "/word/media/图 1.png"},
            ),
            {"word/media/图 1.png": b"fixture image bytes"},
        )
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        process = self.cli("--check-self-contained")
        self.assertEqual(process.returncode, 0, process.stderr)
        status = json.loads(process.stdout)["self_containment"]
        self.assertEqual(status["image_reference_count"], 2)
        self.assertEqual(status["image_dependency_errors"], [])
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_external_image_fails_only_when_requested_even_with_embedded_cache(self):
        body = '<w:p><w:r><w:drawing><a:blip r:embed="img" r:link="remote"/></w:drawing></w:r></w:p>'
        fixture(
            self.path, body,
            relationships(
                {"Id": "img", "Target": "media/image.png"},
                {"Id": "remote", "Target": "https://example.invalid/image.png", "TargetMode": "External"},
            ),
            {"word/media/image.png": b"cached image"},
        )
        normal = self.cli()
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertNotIn("self_containment", json.loads(normal.stdout))
        checked = self.cli("--check-self-contained")
        self.assertEqual(checked.returncode, 1, checked.stderr)
        errors = json.loads(checked.stdout)["self_containment"]["image_dependency_errors"]
        self.assertEqual([item["kind"] for item in errors], ["external_image"])

    def test_missing_relationship_and_missing_media_are_distinguished(self):
        fixture(self.path, drawing("unknown") + drawing(), relationships({"Id": "img", "Target": "media/gone.png"}))
        status = self_containment_status(self.path)
        self.assertEqual(
            [item["kind"] for item in status["image_dependency_errors"]],
            ["missing_relationship", "missing_image_part"],
        )

    def test_parts_outside_body_and_vml_are_checked(self):
        extra = {
            "word/header1.xml": f'<w:hdr {NAMESPACES}>{drawing()}</w:hdr>',
            "word/_rels/header1.xml.rels": relationships({"Id": "img", "Target": "media/header.png"}),
            "word/footer1.xml": f'<w:ftr {NAMESPACES}>{drawing()}</w:ftr>',
            "word/_rels/footer1.xml.rels": relationships({"Id": "img", "Target": "file:///unavailable/footer.png", "TargetMode": "External"}),
            "word/footnotes.xml": f'<w:footnotes {NAMESPACES}><w:p><w:r><w:pict><v:imagedata r:id="legacy"/></w:pict></w:r></w:p></w:footnotes>',
            "word/_rels/footnotes.xml.rels": relationships({"Id": "legacy", "Target": "media/note.png"}),
            "word/media/note.png": b"embedded note image",
        }
        fixture(self.path, extra=extra)
        errors = self_containment_status(self.path)["image_dependency_errors"]
        self.assertEqual({(item["part"], item["kind"]) for item in errors}, {
            ("word/header1.xml", "missing_image_part"), ("word/footer1.xml", "external_image"),
        })

    def test_invalid_targets_are_never_treated_as_local_files(self):
        targets = ("../../../secret.png", "%2e%2e/%2e%2e/secret.png", "media\\image.png", "", "http://[broken")
        for target in targets:
            with self.subTest(target=target):
                fixture(self.path, drawing(), relationships({"Id": "img", "Target": target}))
                self.assertEqual(self_containment_status(self.path)["image_dependency_errors"][0]["kind"], "invalid_image_target")

    def test_source_narrative_is_advisory_and_does_not_remove_legitimate_terms(self):
        values = (
            "根据口述记录，模块完成安装。",
            "现有资料不能证明整机通电完成。",
            "参见外部测试文件。",
            "As noted in the recording, assembly was completed.",
            "记录测试电流和运行时间。",
            "操作完成后保存界面截图；整机验证尚未完成。",
        )
        fixture(self.path, "".join(paragraph(value) for value in values))
        before = self.path.read_bytes()
        process = self.cli("--check-self-contained")
        self.assertEqual(process.returncode, 0, process.stderr)
        candidates = json.loads(process.stdout)["self_containment"]["source_narrative_candidates"]
        self.assertEqual([item["paragraph_index"] for item in candidates], [0, 1, 2, 3])
        self.assertEqual(self.path.read_bytes(), before)

    def test_revision_history_is_preserved_but_body_and_technical_tables_are_reviewed(self):
        def table(header: str, value: str) -> str:
            return f"<w:tbl><w:tr><w:tc>{paragraph(header)}</w:tc></w:tr><w:tr><w:tc>{paragraph(value)}</w:tc></w:tr></w:tbl>"
        fixture(self.path,
                table("版本 修订日期 修订内容", "根据口述记录补充安装过程。")
                + table("Version Date Changes", "According to the transcript, installation was completed.")
                + table("模块 状态", "详见外部测试文件。")
                + paragraph("现有记录表明控制器已安装。"))
        result = audit(self.path, [], [], check_self_contained=True)
        candidates = result["self_containment"]["source_narrative_candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual({item["text"] for item in candidates}, {"详见外部测试文件。", "现有记录表明控制器已安装。"})

    def test_reference_hyperlinks_and_unused_relationships_do_not_fail(self):
        body = '<w:p><w:hyperlink r:id="citation"><w:r><w:t>Reference</w:t></w:r></w:hyperlink></w:p>'
        fixture(self.path, body, relationships(
            {"Id": "citation", "Type": R + "/hyperlink", "Target": "https://example.invalid/reference", "TargetMode": "External"},
            {"Id": "unused", "Target": "https://example.invalid/unused.png", "TargetMode": "External"},
        ))
        self.assertEqual(self_containment_status(self.path)["image_dependency_errors"], [])

    def test_svg_and_strict_drawing_relationships_are_checked(self):
        strict_r = "http://purl.oclc.org/ooxml/officeDocument/relationships"
        body = '<w:p><w:r><w:drawing>'
        body += f'<s:blip xmlns:s="http://purl.oclc.org/ooxml/drawingml/main" xmlns:t="{strict_r}" t:embed="strict"/>'
        body += '<s:svgBlip xmlns:s="http://schemas.microsoft.com/office/drawing/2016/SVG/main" r:embed="svg"/>'
        body += '</w:drawing></w:r></w:p>'
        fixture(self.path, body, relationships(
            {"Id": "strict", "Type": strict_r + "/image", "Target": "media/image.png"},
            {"Id": "svg", "Target": "media/drawing.svg"},
        ), {"word/media/image.png": b"image", "word/media/drawing.svg": b"<svg/>"})
        result = self_containment_status(self.path)
        self.assertEqual(result["image_reference_count"], 2)
        self.assertEqual(result["image_dependency_errors"], [])

    def test_unreadable_relationships_wrong_types_and_direct_sources_are_reported(self):
        fixture(self.path, drawing(), "<broken")
        self.assertIn("unreadable_relationships", {item["kind"] for item in self_containment_status(self.path)["image_dependency_errors"]})
        fixture(self.path, drawing(), relationships({"Id": "img", "Type": R + "/hyperlink", "Target": "media/image.png"}))
        self.assertEqual(self_containment_status(self.path)["image_dependency_errors"][0]["kind"], "wrong_relationship_type")
        fixture(self.path, '<w:p><w:r><w:pict><v:imagedata src="local.png"/></w:pict><w:drawing><a:blip/></w:drawing></w:r></w:p>')
        self.assertEqual({item["kind"] for item in self_containment_status(self.path)["image_dependency_errors"]}, {"unresolved_image_source", "missing_image_reference"})


if __name__ == "__main__":
    unittest.main()
