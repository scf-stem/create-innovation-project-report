#!/usr/bin/env python3
"""Analyze the structure and content density of a reference DOCX report."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import OrderedDict
from pathlib import Path
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"w": W_NS, "a": A_NS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser.parse_args()


def read_xml(archive: zipfile.ZipFile, member: str) -> ET.Element:
    return ET.fromstring(archive.read(member))


def text_of(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.findall(".//w:t", NS)).strip()


def style_maps(archive: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, int]]:
    names: dict[str, str] = {}
    outline_levels: dict[str, int] = {}
    try:
        root = read_xml(archive, "word/styles.xml")
    except KeyError:
        return names, outline_levels
    for style in root.findall(".//w:style", NS):
        style_id = style.get(f"{{{W_NS}}}styleId", "")
        name = style.find("./w:name", NS)
        outline = style.find("./w:pPr/w:outlineLvl", NS)
        if style_id and name is not None:
            names[style_id] = name.get(f"{{{W_NS}}}val", style_id)
        if style_id and outline is not None:
            value = outline.get(f"{{{W_NS}}}val", "")
            if value.isdigit():
                outline_levels[style_id] = int(value) + 1
    return names, outline_levels


def paragraph_style_id(paragraph: ET.Element) -> str:
    style = paragraph.find("./w:pPr/w:pStyle", NS)
    return style.get(f"{{{W_NS}}}val", "") if style is not None else ""


def heading_level(
    paragraph: ET.Element,
    style_names: dict[str, str],
    outline_levels: dict[str, int],
) -> int | None:
    style_id = paragraph_style_id(paragraph)
    style_name = style_names.get(style_id, style_id)
    match = re.search(r"(?:Heading|标题)\s*([1-9])", style_name, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:Heading|标题)([1-9])", style_id, re.I)
    if match:
        return int(match.group(1))
    return outline_levels.get(style_id)


def new_section(title: str, level: int) -> dict:
    return {
        "title": title,
        "level": level,
        "body_characters": 0,
        "body_paragraphs": 0,
        "list_paragraphs": 0,
        "tables": 0,
        "table_rows": 0,
        "images": 0,
        "figure_captions": 0,
        "table_captions": 0,
    }


def analyze(docx: Path) -> dict:
    with zipfile.ZipFile(docx) as archive:
        root = read_xml(archive, "word/document.xml")
        style_names, outline_levels = style_maps(archive)

    body = root.find("./w:body", NS)
    if body is None:
        raise ValueError("word/document.xml has no body")

    sections: OrderedDict[str, dict] = OrderedDict()
    section_key = "前置部分"
    sections[section_key] = new_section(section_key, 0)
    seen_keys: dict[str, int] = {}

    for block in list(body):
        current = sections[section_key]
        if block.tag == f"{{{W_NS}}}p":
            text = text_of(block)
            style_id = paragraph_style_id(block)
            style_name = style_names.get(style_id, style_id)
            style_lower = style_name.lower()
            is_toc = (
                style_lower.startswith("toc")
                or style_name.startswith("目录")
                or block.find(".//w:instrText", NS) is not None
            )
            is_cover = style_lower in ("title", "subtitle") or style_name in ("文档标题", "副标题")
            if is_toc or is_cover:
                continue
            level = heading_level(block, style_names, outline_levels)
            if level is not None and text:
                count = seen_keys.get(text, 0) + 1
                seen_keys[text] = count
                section_key = text if count == 1 else f"{text} [{count}]"
                sections[section_key] = new_section(text, level)
                continue

            current["images"] += len(block.findall(".//a:blip", NS))
            if not text:
                continue
            if re.match(r"^图\s*[A-Za-z0-9一二三四五六七八九十]+(?:[-—]\d+)?", text):
                current["figure_captions"] += 1
                continue
            if re.match(r"^表\s*[A-Za-z0-9一二三四五六七八九十]+(?:[-—]\d+)?", text):
                current["table_captions"] += 1
                continue
            current["body_characters"] += len(re.sub(r"\s+", "", text))
            current["body_paragraphs"] += 1
            if (
                style_lower.startswith("list")
                or "列表" in style_name
                or block.find("./w:pPr/w:numPr", NS) is not None
            ):
                current["list_paragraphs"] += 1
        elif block.tag == f"{{{W_NS}}}tbl":
            current["tables"] += 1
            current["table_rows"] += len(block.findall(".//w:tr", NS))

    totals = {
        key: sum(section[key] for section in sections.values())
        for key in (
            "body_characters",
            "body_paragraphs",
            "list_paragraphs",
            "tables",
            "table_rows",
            "images",
            "figure_captions",
            "table_captions",
        )
    }
    total_chars = totals["body_characters"] or 1
    for section in sections.values():
        section["character_share"] = round(section["body_characters"] / total_chars, 4)

    return {
        "path": str(docx.resolve()),
        "section_count": len(sections),
        "totals": totals,
        "sections": list(sections.values()),
        "note": "DOCX analysis reports content density, not exact rendered page counts.",
    }


def render_markdown(data: dict) -> str:
    lines = [
        "# 参考报告结构分析",
        "",
        f"- 文件：`{data['path']}`",
        f"- 章节单元：{data['section_count']}",
        f"- 正文字符：{data['totals']['body_characters']}",
        f"- 表格：{data['totals']['tables']}",
        f"- 图片：{data['totals']['images']}",
        "",
        "| 章节 | 层级 | 正文字符 | 占比 | 段落 | 表格/行 | 图片 | 图题 | 表题 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for section in data["sections"]:
        lines.append(
            "| {title} | {level} | {body_characters} | {share:.1%} | "
            "{body_paragraphs} | {tables}/{table_rows} | {images} | "
            "{figure_captions} | {table_captions} |".format(
                share=section["character_share"], **section
            )
        )
    lines.extend(["", "> 该统计用于比较章节密度，不代表渲染后的精确页数。", ""])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    docx = args.docx.expanduser().resolve()
    if not docx.is_file():
        raise SystemExit(f"DOCX not found: {docx}")
    data = analyze(docx)
    content = (
        json.dumps(data, ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_markdown(data)
    )
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(output)
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
