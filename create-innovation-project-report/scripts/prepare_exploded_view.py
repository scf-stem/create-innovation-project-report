#!/usr/bin/env python3
"""Validate an exploded-view manifest and produce a deterministic generation spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


VALID_MODES = {"cad-native", "imagegen", "schematic"}
VALID_AXES = {"horizontal", "vertical", "depth", "radial"}
VALID_VIEWS = {"isometric", "front", "side", "top", "perspective"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, help="Write normalized JSON spec")
    parser.add_argument("--prompt-output", type=Path, help="Write image-generation prompt")
    parser.add_argument("--template", action="store_true", help="Print a manifest template")
    return parser.parse_args()


def template() -> dict:
    return {
        "subject": "项目机械组件",
        "mode": "imagegen",
        "reference_images": ["assembly.png"],
        "assembly_source": "",
        "parts": [
            {"id": "1", "name": "外壳", "order": 1, "source_path": ""},
            {"id": "2", "name": "主支架", "order": 2, "source_path": ""},
            {"id": "3", "name": "端部连接件", "order": 3, "source_path": ""},
        ],
        "layout": {
            "view": "isometric",
            "axis": "horizontal",
            "spacing": "medium",
            "background": "white",
            "label_style": "number-only",
            "accent_color": "#246B78",
        },
        "target": {
            "section": "机械结构设计",
            "caption": "图 6-2 机械组件爆炸关系",
            "width_cm": 15.5,
        },
        "output_image": "exploded-view.png",
    }


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def validate_manifest(data: dict, base: Path) -> tuple[dict, list[str]]:
    errors: list[str] = []
    subject = str(data.get("subject", "")).strip()
    if not subject:
        errors.append("subject is required")

    mode = data.get("mode", "imagegen")
    if mode not in VALID_MODES:
        errors.append(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")

    parts = data.get("parts")
    if not isinstance(parts, list) or len(parts) < 2:
        errors.append("parts must contain at least two components")
        parts = []

    normalized_parts = []
    seen_ids: set[str] = set()
    for index, part in enumerate(parts, 1):
        if not isinstance(part, dict):
            errors.append(f"part {index} must be an object")
            continue
        part_id = str(part.get("id", index)).strip()
        name = str(part.get("name", "")).strip()
        if not name:
            errors.append(f"part {part_id} has no name")
        if part_id in seen_ids:
            errors.append(f"duplicate part id: {part_id}")
        seen_ids.add(part_id)
        source_path = str(part.get("source_path", "")).strip()
        resolved_source = None
        if source_path:
            candidate = resolve_path(source_path, base)
            if not candidate.exists():
                errors.append(f"part source not found: {source_path}")
            resolved_source = str(candidate)
        normalized_parts.append(
            {
                "id": part_id,
                "name": name,
                "order": int(part.get("order", index)),
                "source_path": resolved_source,
                "notes": str(part.get("notes", "")).strip(),
            }
        )

    normalized_parts.sort(key=lambda item: (item["order"], item["id"]))
    references = []
    for value in data.get("reference_images", []):
        candidate = resolve_path(str(value), base)
        if not candidate.is_file():
            errors.append(f"reference image not found: {value}")
        references.append(str(candidate))

    assembly_source = str(data.get("assembly_source", "")).strip()
    resolved_assembly = None
    if assembly_source:
        candidate = resolve_path(assembly_source, base)
        if not candidate.exists():
            errors.append(f"assembly source not found: {assembly_source}")
        resolved_assembly = str(candidate)
    if mode == "cad-native" and not resolved_assembly:
        errors.append("cad-native mode requires assembly_source")
    if mode == "imagegen" and not references:
        errors.append("imagegen mode requires at least one reference image")

    layout = data.get("layout", {})
    view = layout.get("view", "isometric")
    axis = layout.get("axis", "horizontal")
    if view not in VALID_VIEWS:
        errors.append(f"unsupported view: {view}")
    if axis not in VALID_AXES:
        errors.append(f"unsupported axis: {axis}")
    label_style = layout.get("label_style", "number-only")
    if label_style not in {"number-only", "number-and-name", "none"}:
        errors.append("label_style must be number-only, number-and-name, or none")

    target = data.get("target", {})
    caption = str(target.get("caption", "")).strip()
    if not caption:
        errors.append("target.caption is required")
    width_cm = float(target.get("width_cm", 15.5))
    if not 5 <= width_cm <= 17:
        errors.append("target.width_cm must be between 5 and 17")

    output_image = str(data.get("output_image", "exploded-view.png")).strip()
    if Path(output_image).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        errors.append("output_image must use PNG or JPEG")

    normalized = {
        "subject": subject,
        "mode": mode,
        "reference_images": references,
        "assembly_source": resolved_assembly,
        "parts": normalized_parts,
        "layout": {
            "view": view,
            "axis": axis,
            "spacing": layout.get("spacing", "medium"),
            "background": layout.get("background", "white"),
            "label_style": label_style,
            "accent_color": layout.get("accent_color", "#246B78"),
        },
        "target": {
            "section": str(target.get("section", "")).strip(),
            "caption": caption,
            "width_cm": width_cm,
        },
        "output_image": str(resolve_path(output_image, base)),
    }
    return normalized, errors


def generation_prompt(spec: dict) -> str:
    part_lines = "；".join(f"{part['id']}={part['name']}" for part in spec["parts"])
    layout = spec["layout"]
    label_instruction = {
        "number-only": "图内仅标数字编号，不写大标题或说明段落",
        "number-and-name": "图内只使用编号和简短零件名称，不写大标题",
        "none": "图内不放任何文字",
    }[layout["label_style"]]
    return (
        f"依据提供的真实项目参考图，生成“{spec['subject']}”工程爆炸图。"
        f"必须保持零件数量、外形、连接关系和相对尺度，不添加资料中不存在的部件。"
        f"零件顺序：{part_lines}。采用{layout['view']}视角，沿{layout['axis']}方向展开，"
        f"间距为{layout['spacing']}，{layout['background']}背景，"
        f"使用克制的工程制图风格和统一线条，强调色为{layout['accent_color']}。"
        f"{label_instruction}。所有零件完整可见，不遮挡、不裁切，不生成尺寸、性能数据、"
        "品牌标识、PPT 边框或测试结果。输出适合正式中文项目报告的高分辨率 PNG。"
    )


def prepare(manifest_path: Path) -> dict:
    path = manifest_path.expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    spec, errors = validate_manifest(data, path.parent)
    if errors:
        raise ValueError("\n".join(errors))
    spec["generation_prompt"] = generation_prompt(spec)
    spec["verification"] = [
        "零件数量与清单一致",
        "外形与真实项目资料一致",
        "展开方向与装配关系正确",
        "图内无重复标题和长段文字",
        "图片没有伪造测试状态或性能数据",
        "题注和正文引用与目标章节一致",
    ]
    return spec


def main() -> int:
    args = parse_args()
    if args.template:
        print(json.dumps(template(), ensure_ascii=False, indent=2))
        return 0
    if not args.manifest:
        raise SystemExit("manifest is required unless --template is used")
    try:
        spec = prepare(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error

    content = json.dumps(spec, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(output)
    else:
        print(content)
    if args.prompt_output:
        prompt_output = args.prompt_output.expanduser().resolve()
        prompt_output.parent.mkdir(parents=True, exist_ok=True)
        prompt_output.write_text(spec["generation_prompt"] + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
