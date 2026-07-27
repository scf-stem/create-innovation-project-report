from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from analyze_reference_docx import analyze  # noqa: E402


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def create_reference_docx(path: Path) -> None:
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>一、项目概述</w:t></w:r></w:p>
    <w:p><w:r><w:t>本项目完成结构设计与控制实现。</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>模块</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    <w:sectPr/>
  </w:body>
</w:document>"""
    styles = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="{W_NS}">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>
  </w:style>
</w:styles>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)


class ReferenceAnalysisTest(unittest.TestCase):
    def test_analyzes_without_python_docx(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "reference.docx"
            create_reference_docx(path)
            result = analyze(path)
            self.assertEqual(result["totals"]["tables"], 1)
            self.assertEqual(result["sections"][1]["title"], "一、项目概述")
            self.assertGreater(result["totals"]["body_characters"], 0)


if __name__ == "__main__":
    unittest.main()
