#!/usr/bin/env python3
"""Append or insert real project images into a DOCX appendix using OOXML."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from image_utils import ImageInfo, inspect_image


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
EMU_PER_CM = 360_000

NS = {"w": W_NS, "wp": WP_NS, "a": A_NS, "pic": PIC_NS}

for prefix, uri in (
    ("w", W_NS),
    ("r", R_NS),
    ("wp", WP_NS),
    ("a", A_NS),
    ("pic", PIC_NS),
    ("pr", REL_NS),
    ("ct", CT_NS),
):
    ET.register_namespace(prefix, uri)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_docx", type=Path)
    parser.add_argument("output_docx", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--allow-unreferenced", action="store_true")
    return parser.parse_args()


def qn(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def text_of(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.findall(".//w:t", NS)).strip()


def xml_bytes(
    root: ET.Element,
    preserve_namespaces_from: bytes | None = None,
    default_namespace: str | None = None,
) -> bytes:
    if default_namespace:
        ET.register_namespace("", default_namespace)
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if not preserve_namespaces_from:
        return data
    original_tag_start = preserve_namespaces_from.find(
        b"<",
        preserve_namespaces_from.find(b"?>") + 2,
    )
    original_tag_end = preserve_namespaces_from.find(b">", original_tag_start)
    serialized_tag_start = data.find(b"<", data.find(b"?>") + 2)
    serialized_tag_end = data.find(b">", serialized_tag_start)
    if original_tag_start < 0 or original_tag_end < 0 or serialized_tag_end < 0:
        return data
    original_opening = preserve_namespaces_from[original_tag_start : original_tag_end + 1]
    serialized_opening = data[serialized_tag_start : serialized_tag_end + 1]
    additions = []
    for prefix, quote, uri in re.findall(
        rb"\sxmlns:([A-Za-z_][A-Za-z0-9_.-]*)=(['\"])(.*?)\2",
        original_opening,
    ):
        marker = b"xmlns:" + prefix + b"="
        if marker not in serialized_opening:
            additions.append(b" xmlns:" + prefix + b'="' + uri + b'"')
    if not additions:
        return data
    return data[:serialized_tag_end] + b"".join(additions) + data[serialized_tag_end:]


def read_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    images = data.get("images")
    if not isinstance(images, list) or not images:
        raise ValueError("manifest.images must contain at least one image")
    return data


def resolve_style_id(styles_root: ET.Element | None, candidates: tuple[str, ...]) -> str | None:
    if styles_root is None:
        return None
    lowered = {candidate.lower() for candidate in candidates}
    for style in styles_root.findall(".//w:style", NS):
        name = style.find("./w:name", NS)
        if name is None:
            continue
        value = name.get(qn(W_NS, "val"), "").lower()
        if value in lowered:
            return style.get(qn(W_NS, "styleId"))
    return None


def add_ppr(
    paragraph: ET.Element,
    *,
    style_id: str | None = None,
    alignment: str | None = None,
    keep_next: bool = False,
) -> ET.Element:
    ppr = ET.SubElement(paragraph, qn(W_NS, "pPr"))
    if style_id:
        ET.SubElement(ppr, qn(W_NS, "pStyle"), {qn(W_NS, "val"): style_id})
    if alignment:
        ET.SubElement(ppr, qn(W_NS, "jc"), {qn(W_NS, "val"): alignment})
    if keep_next:
        ET.SubElement(ppr, qn(W_NS, "keepNext"))
    return ppr


def text_paragraph(
    text: str,
    *,
    style_id: str | None = None,
    alignment: str | None = None,
    keep_next: bool = False,
) -> ET.Element:
    paragraph = ET.Element(qn(W_NS, "p"))
    add_ppr(paragraph, style_id=style_id, alignment=alignment, keep_next=keep_next)
    run = ET.SubElement(paragraph, qn(W_NS, "r"))
    node = ET.SubElement(run, qn(W_NS, "t"))
    node.text = text
    return paragraph


def page_break_paragraph() -> ET.Element:
    paragraph = ET.Element(qn(W_NS, "p"))
    run = ET.SubElement(paragraph, qn(W_NS, "r"))
    ET.SubElement(run, qn(W_NS, "br"), {qn(W_NS, "type"): "page"})
    return paragraph


def is_page_break_paragraph(element: ET.Element) -> bool:
    return (
        element.tag == qn(W_NS, "p")
        and not text_of(element)
        and any(
            node.get(qn(W_NS, "type"), "") == "page"
            for node in element.findall(".//w:br", NS)
        )
    )


def image_paragraph(
    relationship_id: str,
    filename: str,
    alt_text: str,
    info: ImageInfo,
    *,
    width_cm: float,
    max_height_cm: float,
    alignment: str,
    doc_pr_id: int,
) -> ET.Element:
    cx = int(width_cm * EMU_PER_CM)
    cy = int(cx * info.height / info.width)
    max_cy = int(max_height_cm * EMU_PER_CM)
    if cy > max_cy:
        cy = max_cy
        cx = int(cy * info.width / info.height)

    paragraph = ET.Element(qn(W_NS, "p"))
    add_ppr(paragraph, alignment=alignment, keep_next=True)
    run = ET.SubElement(paragraph, qn(W_NS, "r"))
    drawing = ET.SubElement(run, qn(W_NS, "drawing"))
    inline = ET.SubElement(
        drawing,
        qn(WP_NS, "inline"),
        {"distT": "0", "distB": "0", "distL": "0", "distR": "0"},
    )
    ET.SubElement(inline, qn(WP_NS, "extent"), {"cx": str(cx), "cy": str(cy)})
    ET.SubElement(
        inline,
        qn(WP_NS, "docPr"),
        {"id": str(doc_pr_id), "name": filename, "descr": alt_text},
    )
    frame = ET.SubElement(inline, qn(WP_NS, "cNvGraphicFramePr"))
    ET.SubElement(frame, qn(A_NS, "graphicFrameLocks"), {"noChangeAspect": "1"})
    graphic = ET.SubElement(inline, qn(A_NS, "graphic"))
    graphic_data = ET.SubElement(
        graphic,
        qn(A_NS, "graphicData"),
        {"uri": "http://schemas.openxmlformats.org/drawingml/2006/picture"},
    )
    picture = ET.SubElement(graphic_data, qn(PIC_NS, "pic"))
    nv = ET.SubElement(picture, qn(PIC_NS, "nvPicPr"))
    ET.SubElement(
        nv,
        qn(PIC_NS, "cNvPr"),
        {"id": "0", "name": filename, "descr": alt_text},
    )
    ET.SubElement(nv, qn(PIC_NS, "cNvPicPr"))
    fill = ET.SubElement(picture, qn(PIC_NS, "blipFill"))
    ET.SubElement(fill, qn(A_NS, "blip"), {qn(R_NS, "embed"): relationship_id})
    stretch = ET.SubElement(fill, qn(A_NS, "stretch"))
    ET.SubElement(stretch, qn(A_NS, "fillRect"))
    shape = ET.SubElement(picture, qn(PIC_NS, "spPr"))
    transform = ET.SubElement(shape, qn(A_NS, "xfrm"))
    ET.SubElement(transform, qn(A_NS, "off"), {"x": "0", "y": "0"})
    ET.SubElement(transform, qn(A_NS, "ext"), {"cx": str(cx), "cy": str(cy)})
    geometry = ET.SubElement(shape, qn(A_NS, "prstGeom"), {"prst": "rect"})
    ET.SubElement(geometry, qn(A_NS, "avLst"))
    return paragraph


def next_relationship_id(relationships: ET.Element) -> str:
    used = set()
    for relation in list(relationships):
        value = relation.get("Id", "")
        match = re.fullmatch(r"rId(\d+)", value)
        if match:
            used.add(int(match.group(1)))
    candidate = 1
    while candidate in used:
        candidate += 1
    return f"rId{candidate}"


def max_doc_pr_id(document: ET.Element) -> int:
    values = []
    for element in document.findall(".//wp:docPr", NS):
        try:
            values.append(int(element.get("id", "0")))
        except ValueError:
            continue
    return max(values, default=0)


def ensure_content_type(content_types: ET.Element, info: ImageInfo) -> None:
    extension = info.extension.lstrip(".")
    existing = {
        element.get("Extension", "").lower()
        for element in content_types.findall(qn(CT_NS, "Default"))
    }
    if extension not in existing:
        ET.SubElement(
            content_types,
            qn(CT_NS, "Default"),
            {"Extension": extension, "ContentType": info.mime_type},
        )


def normalize_number(value: str) -> str:
    number = value.strip()
    if number.startswith("附图"):
        return re.sub(r"\s+", " ", number)
    return f"附图 {number}"


def insert_appendix(
    input_docx: Path,
    output_docx: Path,
    manifest_path: Path,
    *,
    allow_unreferenced: bool = False,
) -> dict:
    source = input_docx.expanduser().resolve()
    output = output_docx.expanduser().resolve()
    manifest_file = manifest_path.expanduser().resolve()
    if source == output:
        raise ValueError("Output DOCX must differ from input DOCX")
    if not source.is_file():
        raise FileNotFoundError(source)
    manifest = read_manifest(manifest_file)
    base = manifest_file.parent

    with zipfile.ZipFile(source) as archive:
        infos = {info.filename: info for info in archive.infolist()}
        contents = {info.filename: archive.read(info.filename) for info in archive.infolist()}

    document = ET.fromstring(contents["word/document.xml"])
    relationships = ET.fromstring(contents["word/_rels/document.xml.rels"])
    content_types = ET.fromstring(contents["[Content_Types].xml"])
    styles_root = (
        ET.fromstring(contents["word/styles.xml"]) if "word/styles.xml" in contents else None
    )
    body = document.find("./w:body", NS)
    if body is None:
        raise ValueError("word/document.xml has no body")

    heading_style = resolve_style_id(styles_root, ("heading 1", "标题 1", "标题1"))
    caption_style = resolve_style_id(styles_root, ("caption", "题注"))
    appendix_title = str(manifest.get("appendix_title", "附录A 项目实物图片")).strip()
    require_references = bool(manifest.get("require_body_references", True))
    if allow_unreferenced:
        require_references = False

    original_text = text_of(document)
    items = []
    seen_numbers: set[str] = set()
    for index, raw in enumerate(manifest["images"], 1):
        if not isinstance(raw, dict):
            raise ValueError(f"images[{index}] must be an object")
        number = normalize_number(str(raw.get("number", f"A-{index}")))
        if number in seen_numbers:
            raise ValueError(f"Duplicate appendix figure number: {number}")
        seen_numbers.add(number)
        if require_references and number not in original_text:
            raise ValueError(f"Body reference is missing: {number}")
        if any(text_of(p).startswith(number) for p in body.findall("./w:p", NS)):
            raise ValueError(f"Appendix figure already exists: {number}")
        path_value = str(raw.get("path", "")).strip()
        if not path_value:
            raise ValueError(f"{number} has no image path")
        image_path = Path(path_value).expanduser()
        if not image_path.is_absolute():
            image_path = (base / image_path).resolve()
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        info = inspect_image(image_path)
        items.append((raw, number, image_path, info))

    body_children = list(body)
    sect_pr = body.find("./w:sectPr", NS)
    insertion_index = body_children.index(sect_pr) if sect_pr is not None else len(body_children)
    existing_heading_index = None
    for index, child in enumerate(body_children):
        if child.tag == qn(W_NS, "p") and text_of(child) == appendix_title:
            existing_heading_index = index
            break
    nodes: list[ET.Element] = []
    if existing_heading_index is None:
        previous = body_children[insertion_index - 1] if insertion_index > 0 else None
        if manifest.get("start_new_page", True) and (
            previous is None or not is_page_break_paragraph(previous)
        ):
            nodes.append(page_break_paragraph())
        nodes.append(text_paragraph(appendix_title, style_id=heading_style, keep_next=True))
    else:
        insertion_index = existing_heading_index + 1

    existing_media = {
        Path(name).name for name in contents if name.startswith("word/media/")
    }
    new_media: dict[str, bytes] = {}
    next_doc_pr = max_doc_pr_id(document) + 1
    one_per_page = bool(manifest.get("one_image_per_page", True))
    default_width = float(manifest.get("width_cm", 15.5))
    default_max_height = float(manifest.get("max_height_cm", 18.5))
    default_alignment = str(manifest.get("alignment", "center"))
    if default_alignment not in {"left", "center", "right"}:
        raise ValueError("alignment must be left, center, or right")

    inserted = []
    for index, (raw, number, image_path, info) in enumerate(items, 1):
        if index > 1 and one_per_page:
            nodes.append(page_break_paragraph())
        relation_id = next_relationship_id(relationships)
        media_name = f"appendix_image_{index}{info.extension}"
        suffix_index = 2
        while media_name in existing_media or media_name in new_media:
            media_name = f"appendix_image_{index}_{suffix_index}{info.extension}"
            suffix_index += 1
        existing_media.add(media_name)
        ET.SubElement(
            relationships,
            qn(REL_NS, "Relationship"),
            {
                "Id": relation_id,
                "Type": IMAGE_REL_TYPE,
                "Target": f"media/{media_name}",
            },
        )
        ensure_content_type(content_types, info)
        new_media[f"word/media/{media_name}"] = image_path.read_bytes()

        caption = str(raw.get("caption", "")).strip()
        caption_text = f"{number} {caption}".strip()
        description = str(raw.get("description", "")).strip()
        alt_text = str(raw.get("alt_text", caption or number)).strip()
        alignment = str(raw.get("alignment", default_alignment))
        if alignment not in {"left", "center", "right"}:
            raise ValueError(f"Invalid alignment for {number}: {alignment}")
        nodes.append(
            image_paragraph(
                relation_id,
                media_name,
                alt_text,
                info,
                width_cm=float(raw.get("width_cm", default_width)),
                max_height_cm=float(raw.get("max_height_cm", default_max_height)),
                alignment=alignment,
                doc_pr_id=next_doc_pr,
            )
        )
        next_doc_pr += 1
        nodes.append(
            text_paragraph(
                caption_text,
                style_id=caption_style,
                alignment="center",
                keep_next=bool(description),
            )
        )
        if description:
            nodes.append(text_paragraph(f"说明：{description}"))
        inserted.append(
            {
                "number": number,
                "path": str(image_path),
                "media": media_name,
                "width": info.width,
                "height": info.height,
            }
        )

    for offset, node in enumerate(nodes):
        body.insert(insertion_index + offset, node)

    contents["word/document.xml"] = xml_bytes(
        document,
        preserve_namespaces_from=contents["word/document.xml"],
    )
    contents["word/_rels/document.xml.rels"] = xml_bytes(
        relationships,
        default_namespace=REL_NS,
    )
    contents["[Content_Types].xml"] = xml_bytes(
        content_types,
        default_namespace=CT_NS,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in contents.items():
            info = infos[name]
            archive.writestr(info, data)
        for name, data in new_media.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)

    with zipfile.ZipFile(output) as archive:
        ET.fromstring(archive.read("word/document.xml"))
        ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        ET.fromstring(archive.read("[Content_Types].xml"))
        for item in inserted:
            if f"word/media/{item['media']}" not in archive.namelist():
                raise RuntimeError(f"Image was not packaged: {item['media']}")
    return {
        "input": str(source),
        "output": str(output),
        "appendix_title": appendix_title,
        "inserted_count": len(inserted),
        "images": inserted,
    }


def main() -> int:
    args = parse_args()
    try:
        result = insert_appendix(
            args.input_docx,
            args.output_docx,
            args.manifest,
            allow_unreferenced=args.allow_unreferenced,
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
