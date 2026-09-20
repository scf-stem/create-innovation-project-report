#!/usr/bin/env python3
"""Create a report-oriented inventory of a project directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from portable_io import configure_utf8

from image_utils import inspect_image


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "output",
    "outputs",
    ".venv",
    "render",
    "renders",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"}
DOCUMENT_SUFFIXES = {".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx", ".md", ".txt"}
DATA_SUFFIXES = {".csv", ".tsv", ".log", ".db", ".sqlite", ".sqlite3", ".parquet", ".npy", ".npz", ".mat", ".ipynb"}
CAD_SUFFIXES = {".sldprt", ".sldasm", ".slddrw", ".step", ".stp", ".iges", ".igs", ".stl", ".dwg", ".dxf"}
SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".py",
    ".ino",
    ".java",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".vue",
    ".go",
    ".rs",
    ".cs",
    ".kt",
    ".swift",
    ".r",
    ".sql",
    ".sh",
    ".launch",
    ".lua",
}
MODEL_SUFFIXES = {".pt", ".pth", ".onnx", ".weights", ".engine", ".tflite", ".pb"}
CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".xml", ".ini", ".cfg", ".conf", ".rviz", ".urdf", ".xacro", ".ioc"}
ELECTRONICS_SUFFIXES = {".sch", ".brd", ".pcb", ".kicad_sch", ".kicad_pcb", ".uvproj", ".uvprojx", ".uvoptx"}
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}

DOMAIN_KEYWORDS = {
    "机械与结构": ("solidworks", "cad", "机械", "结构", "装配", "外壳", "底盘", "零件"),
    "电路与嵌入式": ("stm32", "mcu", "keil", "电路", "主控", "驱动", "传感器", "motor", "pwm", "usart"),
    "环境感知与控制": ("温度", "湿度", "光照", "土壤", "环境", "dht", "adc", "dac", "relay", "heater", "cooler"),
    "上位机与交互": ("pyqt", "qt", "ui", "hmi", "界面", "屏幕", "交互", "宠物", "game"),
    "视觉与算法": ("opencv", "yolo", "vision", "camera", "视觉", "识别", "检测", "训练", "数据集"),
    "建图与导航": ("ros", "cartographer", "nav2", "slam", "dwa", "teb", "建图", "导航", "路径规划"),
    "实验数据": ("csv", "tsv", "log", "result", "data", "记录", "测量", "标定", "实验"),
    "测试与交付": ("test", "result", "log", "测试", "结果", "验收", "交付"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Project root directory")
    parser.add_argument("--output", type=Path, help="Write inventory to this file")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--include-output", action="store_true", help="Include output/build directories")
    parser.add_argument("--max-files-per-section", type=int, default=300)
    parser.add_argument(
        "--find-duplicates",
        dest="find_duplicates",
        action="store_true",
        help="Identify files with identical content",
    )
    parser.add_argument("--hash", dest="find_duplicates", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--image-metadata", action="store_true", help="Read image width, height, and DPI")
    parser.add_argument("--exclude-dir", action="append", default=[], help="Additional directory basename to skip")
    return parser.parse_args()


def classify_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "图片"
    if suffix in CAD_SUFFIXES:
        return "机械/CAD"
    if suffix in MODEL_SUFFIXES:
        return "模型权重"
    if suffix in ELECTRONICS_SUFFIXES:
        return "电路/工程"
    if suffix in SOURCE_SUFFIXES:
        return "源码"
    if suffix in CONFIG_SUFFIXES:
        return "配置"
    if suffix in DOCUMENT_SUFFIXES:
        return "文档"
    if suffix in DATA_SUFFIXES:
        return "实验数据"
    if suffix in ARCHIVE_SUFFIXES:
        return "压缩包"
    return "其他"


def classify_domains(path: Path) -> list[str]:
    normalized = str(path).lower()
    matches = [
        domain
        for domain, keywords in DOMAIN_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    ]
    return matches or ["未分类"]


def iter_files(root: Path, include_output: bool, exclude_dirs=(), errors=None):
    excluded = (set() if include_output else DEFAULT_EXCLUDED_DIRS) | set(exclude_dirs)
    errors = errors if errors is not None else []
    for current, directories, names in os.walk(root, followlinks=False, onerror=lambda error: errors.append(str(error))):
        directories[:] = sorted(name for name in directories if name not in excluded and not name.startswith('.') and not (Path(current) / name).is_symlink())
        for name in sorted(names):
            path = Path(current) / name
            if not name.startswith('.') and not path.is_symlink() and path.is_file():
                yield path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_metadata(path: Path) -> dict:
    try:
        info = inspect_image(path)
        return info.to_dict()
    except Exception as error:
        return {"metadata_error": str(error)}


def build_inventory(
    root: Path,
    include_output: bool,
    compute_hash: bool,
    include_image_metadata: bool,
    exclude_dirs=(),
) -> dict:
    files = []
    errors = []
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    for path in iter_files(root, include_output, exclude_dirs, errors):
        relative = path.relative_to(root)
        try:
            size = path.stat().st_size
            digest = sha256_file(path) if compute_hash else None
        except OSError as error:
            errors.append(f"{relative}: {error}")
            continue
        item = {
            "path": relative.as_posix(),
            "type": classify_type(relative),
            "domains": classify_domains(relative),
            "bytes": size,
        }
        if compute_hash:
            item["sha256"] = digest
        if include_image_metadata and item["type"] == "图片":
            item["image"] = image_metadata(path)
        files.append(item)

    files.sort(key=lambda item: item["path"].lower())
    type_counts = Counter(item["type"] for item in files)
    domain_counts = Counter(domain for item in files for domain in item["domains"])
    duplicate_groups = []
    if compute_hash:
        by_hash = defaultdict(list)
        for item in files:
            by_hash[item["sha256"]].append(item["path"])
        duplicate_groups = [
            {"sha256": digest, "paths": paths}
            for digest, paths in sorted(by_hash.items())
            if len(paths) > 1
        ]
    duplicate_file_count = sum(len(group["paths"]) - 1 for group in duplicate_groups)

    return {
        "root": str(root.resolve()),
        "file_count": len(files),
        "type_counts": dict(sorted(type_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_file_count": duplicate_file_count,
        "unique_content_count": len(files) - duplicate_file_count,
        "duplicate_groups": duplicate_groups,
        "files": files,
        "warnings": errors,
        "complete": not errors,
    }


def render_markdown(data: dict, limit: int) -> str:
    lines = [
        "# 项目资料盘点",
        "",
        f"- 项目根目录：`{data['root']}`",
        f"- 纳入文件数：{data['file_count']}",
        "",
        "## 文件类型统计",
        "",
        "| 类型 | 数量 |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in data["type_counts"].items())
    lines.extend(["", "## 领域线索统计", "", "| 领域 | 数量 |", "|---|---:|"])
    lines.extend(f"| {name} | {count} |" for name, count in data["domain_counts"].items())

    by_domain = defaultdict(list)
    for item in data["files"]:
        for domain in item["domains"]:
            by_domain[domain].append(item)

    lines.extend(["", "## 按领域列出资料", ""])
    for domain in sorted(by_domain):
        items = by_domain[domain]
        lines.extend([f"### {domain}", "", "| 路径 | 类型 | 大小（字节） |", "|---|---|---:|"])
        for item in items[:limit]:
            escaped_path = item["path"].replace("|", "\\|")
            lines.append(f"| `{escaped_path}` | {item['type']} | {item['bytes']} |")
        if len(items) > limit:
            lines.append(f"| ……另有 {len(items) - limit} 个文件 |  |  |")
        lines.append("")

    image_items = [item for item in data["files"] if item["type"] == "图片"]
    lines.extend(["## 候选项目图片", "", "| 路径 | 像素尺寸 | 领域线索 |", "|---|---:|---|"])
    for item in image_items[:limit]:
        escaped_path = item["path"].replace("|", "\\|")
        image = item.get("image", {})
        dimensions = (
            f"{image.get('width')}×{image.get('height')}"
            if image.get("width") and image.get("height")
            else "未读取"
        )
        lines.append(f"| `{escaped_path}` | {dimensions} | {'、'.join(item['domains'])} |")
    if len(image_items) > limit:
        lines.append(f"| ……另有 {len(image_items) - limit} 张图片 |  |  |")
    if data["duplicate_groups"]:
        lines.extend(["", "## 内容相同的重复文件", "", "| 内容标识 | 路径 |", "|---|---|"])
        for group in data["duplicate_groups"][:limit]:
            paths = "<br>".join(f"`{path}`" for path in group["paths"])
            lines.append(f"| `{group['sha256'][:16]}…` | {paths} |")
        if len(data["duplicate_groups"]) > limit:
            lines.append(f"| ……另有 {len(data['duplicate_groups']) - limit} 组 |  |")
    lines.append("")
    if data.get("warnings"):
        lines.extend(["## 未能读取的资料", "", *[f"- {warning}" for warning in data["warnings"]], ""])
    return "\n".join(lines)


def main() -> int:
    configure_utf8()
    args = parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Project root is not a directory: {root}")

    data = build_inventory(
        root,
        args.include_output,
        compute_hash=args.find_duplicates,
        include_image_metadata=args.image_metadata,
        exclude_dirs=args.exclude_dir,
    )
    if args.format == "json":
        content = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        content = render_markdown(data, args.max_files_per_section)

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
