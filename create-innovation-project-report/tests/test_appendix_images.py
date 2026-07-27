from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from appendix_images import IMAGE_REL_TYPE, insert_appendix  # noqa: E402
from audit_docx import audit  # noqa: E402


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
NS = {"w": W_NS, "wp": WP_NS, "pr": REL_NS}


def png_bytes(width: int = 8, height: int = 6) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + b"\x33\x66\x99" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def create_minimal_docx(path: Path, body_text: str, trailing_page_break: bool = False) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    trailing_break = "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>" if trailing_page_break else ""
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:mc="{MC_NS}" xmlns:w14="{W14_NS}" mc:Ignorable="w14">
  <w:body>
    <w:p><w:r><w:t>{body_text}</w:t></w:r></w:p>
    {trailing_break}
    <w:sectPr/>
  </w:body>
</w:document>"""
    document_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
    styles = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
  <w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/></w:style>
</w:styles>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        archive.writestr("word/styles.xml", styles)


class AppendixImagesTest(unittest.TestCase):
    def test_inserts_image_caption_alt_text_and_relationship(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.docx"
            output = root / "output.docx"
            image = root / "project.png"
            manifest = root / "appendix.json"
            create_minimal_docx(source, "机械结构见附图 A-1。")
            image.write_bytes(png_bytes())
            manifest.write_text(
                json.dumps(
                    {
                        "appendix_title": "附录A 项目实物图片",
                        "require_body_references": True,
                        "images": [
                            {
                                "path": "project.png",
                                "number": "A-1",
                                "caption": "项目样机整体外观",
                                "description": "可见主体结构和传感器。",
                                "alt_text": "项目样机整体外观",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = insert_appendix(source, output, manifest)
            self.assertEqual(result["inserted_count"], 1)
            audit_result = audit(
                output,
                [],
                [],
                check_cross_references=True,
            )
            self.assertIn("附图A-1", audit_result["cross_references"]["caption_targets"])
            self.assertIn("附图A-1", audit_result["cross_references"]["body_references"])
            self.assertEqual(audit_result["cross_references"]["missing_targets"], [])
            with zipfile.ZipFile(output) as archive:
                self.assertIn("word/media/appendix_image_1.png", archive.namelist())
                document = ET.fromstring(archive.read("word/document.xml"))
                self.assertIn(b"xmlns:w14=", archive.read("word/document.xml"))
                relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
                visible_text = "".join(document.itertext())
                self.assertIn("附录A 项目实物图片", visible_text)
                self.assertIn("附图 A-1 项目样机整体外观", visible_text)
                self.assertIn("说明：可见主体结构和传感器。", visible_text)
                doc_pr = document.find(".//wp:docPr", NS)
                self.assertIsNotNone(doc_pr)
                self.assertEqual(doc_pr.get("descr"), "项目样机整体外观")
                image_relations = [
                    relation
                    for relation in list(relationships)
                    if relation.get("Type") == IMAGE_REL_TYPE
                ]
                self.assertEqual(len(image_relations), 1)

    def test_requires_body_reference_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.docx"
            output = root / "output.docx"
            image = root / "project.png"
            manifest = root / "appendix.json"
            create_minimal_docx(source, "机械结构说明。")
            image.write_bytes(png_bytes())
            manifest.write_text(
                json.dumps(
                    {
                        "images": [
                            {"path": "project.png", "number": "A-1", "caption": "整体外观"}
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Body reference is missing"):
                insert_appendix(source, output, manifest)

    def test_does_not_duplicate_existing_trailing_page_break(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.docx"
            output = root / "output.docx"
            image = root / "project.png"
            manifest = root / "appendix.json"
            create_minimal_docx(source, "参见附图 A-1。", trailing_page_break=True)
            image.write_bytes(png_bytes())
            manifest.write_text(
                json.dumps(
                    {
                        "start_new_page": True,
                        "images": [
                            {"path": "project.png", "number": "A-1", "caption": "整体外观"}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            insert_appendix(source, output, manifest)
            with zipfile.ZipFile(output) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
            page_breaks = [
                node
                for node in document.findall(".//w:br", NS)
                if node.get(f"{{{W_NS}}}type") == "page"
            ]
            self.assertEqual(len(page_breaks), 1)


if __name__ == "__main__":
    unittest.main()
