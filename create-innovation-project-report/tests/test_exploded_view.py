from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from prepare_exploded_view import prepare  # noqa: E402


def png_bytes(width: int = 4, height: int = 3) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + b"\x88\x99\xaa" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class ExplodedViewSpecTest(unittest.TestCase):
    def test_prepares_evidence_bound_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "assembly.png").write_bytes(png_bytes())
            manifest = {
                "subject": "伸缩杆组件",
                "mode": "imagegen",
                "reference_images": ["assembly.png"],
                "parts": [
                    {"id": "1", "name": "外管", "order": 1},
                    {"id": "2", "name": "中管", "order": 2},
                    {"id": "3", "name": "内管", "order": 3},
                ],
                "layout": {
                    "view": "isometric",
                    "axis": "horizontal",
                    "label_style": "number-only",
                },
                "target": {
                    "section": "机械结构设计",
                    "caption": "图 6-2 伸缩杆组件爆炸关系",
                    "width_cm": 15.5,
                },
                "output_image": "exploded.png",
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            spec = prepare(path)

            self.assertEqual([part["name"] for part in spec["parts"]], ["外管", "中管", "内管"])
            self.assertIn("不添加资料中不存在的部件", spec["generation_prompt"])
            self.assertIn("不写大标题", spec["generation_prompt"])
            self.assertTrue(spec["output_image"].endswith("exploded.png"))
            self.assertEqual(spec["target"]["section"], "机械结构设计")

    def test_rejects_duplicate_part_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "assembly.png").write_bytes(png_bytes())
            manifest = {
                "subject": "组件",
                "mode": "imagegen",
                "reference_images": ["assembly.png"],
                "parts": [
                    {"id": "1", "name": "零件甲"},
                    {"id": "1", "name": "零件乙"},
                ],
                "target": {"caption": "图 1-1 组件爆炸关系", "width_cm": 12},
                "output_image": "exploded.png",
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate part id"):
                prepare(path)


if __name__ == "__main__":
    unittest.main()
