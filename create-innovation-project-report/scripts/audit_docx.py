#!/usr/bin/env python3
"""Audit a DOCX project report without changing the document."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from portable_io import configure_utf8
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W_NS, "r": REL_NS}
DEFAULT_FORBIDDEN = ("资料依据", "报告编写口径", "编写说明", "AI生成说明", "自检说明")
METRIC_PATTERNS = (
    re.compile(r"(准确率|识别率|成功率|稳定性).{0,12}\d+(?:\.\d+)?%"),
    re.compile(
        r"\d+(?:\.\d+)?\s*(?:%RH|℃|°C|V|mV|A|mA|W|Hz|kHz|MHz|ms|毫秒|"
        r"fps|帧/秒|km/h|m/s|米/秒|min|分钟|小时|h|lx|lux)"
    ),
    re.compile(r"(显著提升|高精度|实时运行|稳定运行|完全满足)"),
)
NUMBER_TOKEN = r"(?:[A-Za-z]\s*[-—.]?\s*\d+|\d+(?:\s*[-—.]\s*\d+)?)"
LABEL_TOKEN = r"(?:附图|图|表|\bAppendix Figure|\bFigure|\bFig\.|\bTable)"
CAPTION_RE = re.compile(rf"^({LABEL_TOKEN})\s*({NUMBER_TOKEN})", re.I)
REFERENCE_RE = re.compile(rf"({LABEL_TOKEN})\s*({NUMBER_TOKEN})", re.I)
PROJECT_REPORT_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9·（）()_-]{2,50}项目综合实践报告)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", type=Path)
    parser.add_argument("--project-report", action="store_true", help="Enable project-report checks")
    parser.add_argument(
        "--compare-tables-with",
        dest="compare_tables_with",
        type=Path,
        help="Compare table text with a previous DOCX",
    )
    parser.add_argument(
        "--baseline-tables",
        dest="compare_tables_with",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--required-heading", action="append", default=[])
    parser.add_argument("--forbid", action="append", default=[])
    parser.add_argument("--expected-project-name", help="Expected project name in cover/core identity")
    parser.add_argument("--forbid-project-name", action="append", default=[])
    parser.add_argument("--require-toc", action="store_true", help="Require an updateable TOC field")
    parser.add_argument("--check-cross-references", action="store_true")
    parser.add_argument("--check-body-indent", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def open_xml(docx: Path, member: str) -> ET.Element:
    with zipfile.ZipFile(docx) as archive:
        return ET.fromstring(archive.read(member))


def text_of(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.findall(".//w:t", NS)).strip()


def paragraph_style(paragraph: ET.Element) -> str:
    style = paragraph.find("./w:pPr/w:pStyle", NS)
    return style.get(f"{{{W_NS}}}val", "") if style is not None else ""


def style_name_map(docx: Path) -> dict[str, str]:
    try:
        root = open_xml(docx, "word/styles.xml")
    except KeyError:
        return {}
    result = {}
    for style in root.findall(".//w:style", NS):
        style_id = style.get(f"{{{W_NS}}}styleId", "")
        name = style.find("./w:name", NS)
        if style_id and name is not None:
            result[style_id] = name.get(f"{{{W_NS}}}val", style_id)
    return result


def table_text_hash(root: ET.Element) -> tuple[int, str]:
    table_texts = []
    for table in root.findall(".//w:tbl", NS):
        cells = [text_of(cell) for cell in table.findall(".//w:tc", NS)]
        table_texts.append("\x1f".join(cells))
    digest = hashlib.sha256("\x1e".join(table_texts).encode("utf-8")).hexdigest()
    return len(table_texts), digest


def image_count(docx: Path) -> int:
    with zipfile.ZipFile(docx) as archive:
        return sum(name.startswith("word/media/") and not name.endswith("/") for name in archive.namelist())


def package_texts(docx: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    with zipfile.ZipFile(docx) as archive:
        members = [
            name
            for name in archive.namelist()
            if (
                name == "word/document.xml"
                or name.startswith("word/header")
                or name.startswith("word/footer")
                or name in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")
                or name in ("docProps/core.xml", "docProps/custom.xml")
            )
            and name.endswith(".xml")
        ]
        for name in members:
            try:
                root = ET.fromstring(archive.read(name))
                texts[name] = "".join(root.itertext())
            except ET.ParseError:
                texts[name] = ""
    return texts


def toc_status(docx: Path) -> dict:
    root = open_xml(docx, "word/document.xml")
    instructions, stack = [], []
    valid_complex = False
    simple = [node.get(f"{{{W_NS}}}instr", "").strip() for node in root.findall(".//w:fldSimple", NS)]
    simple = [value for value in simple if re.match(r"TOC(?:\s|$)", value, re.I)]
    for node in root.iter():
        if node.tag == f"{{{W_NS}}}fldChar":
            kind = node.get(f"{{{W_NS}}}fldCharType", "")
            if kind == "begin":
                stack.append({"text": "", "separated": False})
            elif kind == "separate" and stack:
                stack[-1]["separated"] = True
            elif kind == "end" and stack:
                field = stack.pop()
                instruction = field["text"].strip()
                if re.match(r"TOC(?:\s|$)", instruction, re.I):
                    instructions.append(instruction)
                    valid_complex = valid_complex or field["separated"]
        elif node.tag == f"{{{W_NS}}}instrText" and stack and not stack[-1]["separated"]:
            stack[-1]["text"] += node.text or ""
    instructions.extend(simple)
    try:
        settings = open_xml(docx, "word/settings.xml")
        update = settings.find(".//w:updateFields", NS)
        update_fields = (
            update is not None
            and update.get(f"{{{W_NS}}}val", "true").lower() not in ("0", "false", "off")
        )
    except KeyError:
        update_fields = False
    return {
        "instructions": instructions,
        "has_begin_separate_end": valid_complex,
        "update_fields": update_fields,
        "valid": valid_complex or bool(simple),
    }


def normalize_ref(kind: str, number: str) -> str:
    kind = {"figure": "Figure", "fig.": "Figure", "appendix figure": "Appendix Figure", "table": "Table"}.get(kind.lower(), kind)
    return kind + re.sub(r"\s+", "", number).replace("—", "-").replace(".", "-")


def direct_first_line_chars(paragraph: ET.Element) -> tuple[str | None, str | None]:
    ind = paragraph.find("./w:pPr/w:ind", NS)
    if ind is None:
        return None, None
    return ind.get(f"{{{W_NS}}}firstLineChars"), ind.get(f"{{{W_NS}}}firstLine")


def audit(
    docx: Path,
    required_headings: list[str],
    forbidden: list[str],
    *,
    expected_project_name: str | None = None,
    forbidden_project_names: list[str] | None = None,
    require_toc: bool = False,
    check_cross_references: bool = False,
    check_body_indent: bool = False,
) -> dict:
    root = open_xml(docx, "word/document.xml")
    body = root.find("w:body", NS)
    if body is None:
        raise ValueError("word/document.xml has no body")

    all_paragraphs = body.findall(".//w:p", NS)
    table_paragraphs = {
        paragraph
        for table in body.findall(".//w:tbl", NS)
        for paragraph in table.findall(".//w:p", NS)
    }
    body_paragraphs = [p for p in all_paragraphs if p not in table_paragraphs]
    styles = style_name_map(docx)
    headings = []
    captions = []
    body_texts = []
    caption_refs: set[str] = set()
    body_refs: set[str] = set()
    indent_candidates = []
    indent_failures = []

    for index, paragraph in enumerate(body_paragraphs):
        text = text_of(paragraph)
        if not text:
            continue
        style_id = paragraph_style(paragraph)
        style = styles.get(style_id, style_id)
        style_lower = style.lower()
        if style_lower.startswith("heading") or style.startswith("标题"):
            headings.append(text)
        elif CAPTION_RE.match(text):
            captions.append(text)
            match = CAPTION_RE.match(text)
            if match:
                caption_refs.add(normalize_ref(match.group(1), match.group(2)))
        else:
            body_texts.append(text)
            for match in REFERENCE_RE.finditer(text):
                body_refs.add(normalize_ref(match.group(1), match.group(2)))
            if check_body_indent:
                ppr = paragraph.find("./w:pPr", NS)
                centered = (
                    ppr is not None
                    and ppr.find("./w:jc", NS) is not None
                    and ppr.find("./w:jc", NS).get(f"{{{W_NS}}}val", "")
                    in ("center", "right")
                )
                is_list = (
                    (ppr is not None and ppr.find("./w:numPr", NS) is not None)
                    or style_lower.startswith("list")
                    or "列表" in style
                )
                is_code = ppr is not None and ppr.find("./w:shd", NS) is not None
                is_toc = style_lower.startswith("toc") or style.startswith("目录")
                is_cover_style = style_lower in ("title", "subtitle") or style in ("文档标题", "副标题")
                has_field = paragraph.find(".//w:fldChar", NS) is not None or paragraph.find(".//w:instrText", NS) is not None
                if (
                    not centered
                    and not is_list
                    and not is_code
                    and not is_toc
                    and not is_cover_style
                    and not has_field
                    and not text.startswith("关键词：")
                ):
                    chars, twips = direct_first_line_chars(paragraph)
                    try:
                        twips_ok = twips is not None and int(twips) >= 400
                    except ValueError:
                        twips_ok = False
                    ok = chars == "200" or twips_ok
                    indent_candidates.append(index)
                    if not ok:
                        indent_failures.append(
                            {"paragraph_index": index, "text": text[:120], "firstLineChars": chars, "firstLine": twips}
                        )

    joined_text = "\n".join(text_of(p) for p in all_paragraphs if text_of(p))
    table_count, table_hash = table_text_hash(root)
    forbidden_hits = {term: joined_text.count(term) for term in forbidden if term in joined_text}
    missing_headings = [heading for heading in required_headings if not any(heading in h for h in headings)]
    metric_candidates = []
    for paragraph in body_texts:
        if any(pattern.search(paragraph) for pattern in METRIC_PATTERNS):
            metric_candidates.append(paragraph)

    parts = package_texts(docx)
    all_package_text = "\n".join(parts.values())
    forbidden_project_names = forbidden_project_names or []
    project_identity_hits = {
        name: [part for part, text in parts.items() if name in text]
        for name in forbidden_project_names
        if name and name in all_package_text
    }
    identity_candidates = sorted(set(PROJECT_REPORT_RE.findall(all_package_text)))
    unexpected_identity_candidates = []
    if expected_project_name:
        unexpected_identity_candidates = [
            item
            for item in identity_candidates
            if expected_project_name not in item and item not in expected_project_name
        ]

    toc = toc_status(docx)
    missing_cross_refs = sorted(body_refs - caption_refs) if check_cross_references else []
    unreferenced_captions = sorted(caption_refs - body_refs) if check_cross_references else []

    return {
        "path": str(docx.resolve()),
        "paragraph_count": len(all_paragraphs),
        "body_paragraph_count": len(body_paragraphs),
        "heading_count": len(headings),
        "headings": headings,
        "table_count": table_count,
        "table_text_sha256": table_hash,
        "image_count": image_count(docx),
        "caption_count": len(captions),
        "captions": captions,
        "missing_required_headings": missing_headings,
        "forbidden_hits": forbidden_hits,
        "metric_claim_candidates": metric_candidates,
        "project_identity": {
            "expected": expected_project_name,
            "expected_present": (
                expected_project_name in all_package_text if expected_project_name else None
            ),
            "forbidden_hits": project_identity_hits,
            "report_title_candidates": identity_candidates,
            "unexpected_report_title_candidates": unexpected_identity_candidates,
        },
        "toc": toc,
        "cross_references": {
            "caption_targets": sorted(caption_refs),
            "body_references": sorted(body_refs),
            "missing_targets": missing_cross_refs,
            "unreferenced_captions": unreferenced_captions,
        },
        "body_indent": {
            "candidate_count": len(indent_candidates),
            "failure_count": len(indent_failures),
            "failures": indent_failures[:50],
        },
        "checks_requested": {
            "require_toc": require_toc,
            "check_cross_references": check_cross_references,
            "check_body_indent": check_body_indent,
        },
    }


def main() -> int:
    configure_utf8()
    args = parse_args()
    docx = args.docx.expanduser().resolve()
    if not docx.is_file():
        raise SystemExit(f"DOCX not found: {docx}")

    forbidden = list(args.forbid)
    if args.project_report:
        forbidden.extend(term for term in DEFAULT_FORBIDDEN if term not in forbidden)
    result = audit(
        docx,
        args.required_heading,
        forbidden,
        expected_project_name=args.expected_project_name,
        forbidden_project_names=args.forbid_project_name,
        require_toc=args.require_toc,
        check_cross_references=args.check_cross_references,
        check_body_indent=args.check_body_indent,
    )

    if args.compare_tables_with:
        previous_docx = args.compare_tables_with.expanduser().resolve()
        if not previous_docx.is_file():
            raise SystemExit(f"Previous DOCX not found: {previous_docx}")
        previous_result = audit(previous_docx, [], [])
        result["comparison_tables"] = {
            "path": str(previous_docx),
            "table_count": previous_result["table_count"],
            "table_text_sha256": previous_result["table_text_sha256"],
            "matches": (
                result["table_count"] == previous_result["table_count"]
                and result["table_text_sha256"] == previous_result["table_text_sha256"]
            ),
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"DOCX: {result['path']}")
        print(
            "结构: "
            f"{result['heading_count']} 个标题, "
            f"{result['table_count']} 个表格, "
            f"{result['image_count']} 个媒体文件, "
            f"{result['caption_count']} 个题注"
        )
        print(f"表格内容检查值: {result['table_text_sha256']}")
        if result["missing_required_headings"]:
            print("缺少标题: " + "；".join(result["missing_required_headings"]))
        if result["forbidden_hits"]:
            hits = "；".join(f"{term}×{count}" for term, count in result["forbidden_hits"].items())
            print("需复核的元叙事词语: " + hits)
        if result["metric_claim_candidates"]:
            print("需核对原始资料的指标或效果表述:")
            for text in result["metric_claim_candidates"][:20]:
                print(f"- {text[:180]}")
        identity = result["project_identity"]
        if identity["unexpected_report_title_candidates"]:
            print("疑似残留的其他项目名称: " + "；".join(identity["unexpected_report_title_candidates"]))
        if identity["forbidden_hits"]:
            print(
                "命中的禁用项目名称: "
                + "；".join(f"{name}({','.join(parts)})" for name, parts in identity["forbidden_hits"].items())
            )
        if args.require_toc:
            print("可自动更新目录: " + ("是" if result["toc"]["valid"] else "否"))
            print("打开文档时更新目录: " + ("是" if result["toc"]["update_fields"] else "否"))
        if args.check_cross_references:
            if result["cross_references"]["missing_targets"]:
                print("正文引用缺少题注目标: " + "；".join(result["cross_references"]["missing_targets"]))
            if result["cross_references"]["unreferenced_captions"]:
                print("未在正文引用的题注: " + "；".join(result["cross_references"]["unreferenced_captions"]))
        if args.check_body_indent:
            print(
                "正文首行缩进: "
                f"{result['body_indent']['candidate_count'] - result['body_indent']['failure_count']}/"
                f"{result['body_indent']['candidate_count']} 通过"
            )
        if "comparison_tables" in result:
            print("表格与上一版一致: " + ("是" if result["comparison_tables"]["matches"] else "否"))

    has_error = bool(result["missing_required_headings"] or result["forbidden_hits"])
    identity = result["project_identity"]
    if identity["forbidden_hits"] or identity["unexpected_report_title_candidates"]:
        has_error = True
    if args.expected_project_name and not identity["expected_present"]:
        has_error = True
    if args.require_toc and (not result["toc"]["valid"] or not result["toc"]["update_fields"]):
        has_error = True
    if args.check_cross_references and result["cross_references"]["missing_targets"]:
        has_error = True
    if args.check_body_indent and result["body_indent"]["failure_count"]:
        has_error = True
    if "comparison_tables" in result and not result["comparison_tables"]["matches"]:
        has_error = True
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
