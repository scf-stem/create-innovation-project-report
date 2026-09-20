"""Versioned, dependency-free configuration shared by report tools."""
from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path


DEFAULTS = {
    "schema_version": 1,
    "project": {"name": "", "root": ".", "domain": "general", "stage": "prototype"},
    "task": {"mode": "create", "language": "zh-CN", "audience": "technical", "depth": "standard", "previous": None},
    "output": {"directory": "output/doc", "format": "docx", "report_label": "综合实践报告", "date": None, "version": None},
    "document": {"paper": "A4", "toc": True, "revision_history": True, "body_page_start": 1, "font": None},
    "modules": {"data": "auto", "visuals": "auto", "appendix": "auto", "polish": "auto"},
    "quality": {"render": "preferred", "max_pages_without_visual": 3},
    "runtime": {"agent": "generic", "offline": False, "capabilities": {"document_writer": "auto", "renderer": "auto", "image_generation": "auto"}},
    "extensions": {},
}
MODES = {"create", "revise", "audit", "outline", "visuals"}
DOMAINS = {"general", "software", "hardware", "research", "data", "product", "mixed"}
AGENTS = {"generic", "codex", "claude-code", "gemini-cli", "cursor", "copilot"}


def merge_config(base: dict, updates: dict, prefix: str = "") -> dict:
    if not isinstance(updates, dict):
        raise ValueError(f"{prefix or 'config'} must be an object")
    result = copy.deepcopy(base)
    for key, value in updates.items():
        field = f"{prefix}.{key}" if prefix else key
        if key not in base:
            raise ValueError(f"Unknown configuration field: {field}")
        if field == "extensions":
            if not isinstance(value, dict):
                raise ValueError("extensions must be an object")
            result[key] = copy.deepcopy(value)
        elif isinstance(base[key], dict):
            result[key] = merge_config(base[key], value, field)
        else:
            result[key] = value
    return result


def choice(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")


def filename_part(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    if value != value.strip() or value.endswith('.') or re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ValueError(f"{field} contains characters unsafe in cross-platform filenames")
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value):
        raise ValueError(f"{field} is a reserved device name")
    return value


def resolve_path(value, base, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty path string")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def load_config(path: Path | None = None, overrides: dict | None = None) -> dict:
    """Resolve config-relative project paths, then project-relative output paths. No writes."""
    path = path.expanduser().resolve() if path else None
    base = path.parent if path else Path.cwd()
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path else {}
    config = merge_config(DEFAULTS, data)
    if overrides:
        config = merge_config(config, overrides)
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("Unsupported schema_version; expected 1")
    project, task, output = config["project"], config["task"], config["output"]
    filename_part(project["name"], "project.name")
    filename_part(output["report_label"], "output.report_label")
    choice(project["domain"], DOMAINS, "project.domain")
    choice(project["stage"], {"concept", "prototype", "validated", "deployed"}, "project.stage")
    choice(task["mode"], MODES, "task.mode")
    choice(task["depth"], {"brief", "standard", "detailed"}, "task.depth")
    for key in ("language", "audience"):
        if not isinstance(task[key], str) or not task[key].strip():
            raise ValueError(f"task.{key} must be nonempty text")
    choice(output["format"], {"docx", "markdown", "pdf"}, "output.format")
    choice(config["document"]["paper"], {"A4", "Letter"}, "document.paper")
    choice(config["quality"]["render"], {"required", "preferred", "skip"}, "quality.render")
    choice(config["runtime"]["agent"], AGENTS, "runtime.agent")
    for group in (config["modules"], config["runtime"]["capabilities"]):
        for key, value in group.items():
            if type(value) is not bool and value != "auto":
                raise ValueError(f"{key} must be true, false or 'auto'")
    for group, key in (("document", "toc"), ("document", "revision_history"), ("runtime", "offline")):
        if type(config[group][key]) is not bool:
            raise ValueError(f"{group}.{key} must be a boolean")
    for group, key in (("document", "body_page_start"), ("quality", "max_pages_without_visual")):
        if type(config[group][key]) is not int or config[group][key] < 1:
            raise ValueError(f"{group}.{key} must be a positive integer")
    font = config["document"]["font"]
    if font is not None and (not isinstance(font, str) or not font.strip()):
        raise ValueError("document.font must be null or nonempty text")
    if output["version"] is not None:
        if not isinstance(output["version"], str) or not re.fullmatch(r"v\d+\.\d+(?:\.\d+)?", output["version"]):
            raise ValueError("output.version must resemble v1.0 or v1.0.1")
    if output["date"] is not None:
        if not isinstance(output["date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", output["date"]):
            raise ValueError("output.date must use YYYY-MM-DD")
        date.fromisoformat(output["date"])
    else:
        output["date"] = date.today().isoformat()
    root = resolve_path(project["root"], base, "project.root")
    if not root.is_dir():
        raise ValueError(f"project.root is not an existing directory: {root}")
    project["root"] = str(root)
    output["directory"] = str(resolve_path(output["directory"], root, "output.directory"))
    if task["previous"] is not None:
        previous = resolve_path(task["previous"], base, "task.previous")
        if not previous.is_file():
            raise ValueError(f"task.previous is not an existing file: {previous}")
        task["previous"] = str(previous)
    if task["mode"] in {"revise", "audit", "visuals"} and not task["previous"]:
        raise ValueError(f"task.previous is required for mode {task['mode']}")
    return config


def output_path(config: dict) -> Path | None:
    """Audit returns findings, not a replacement document."""
    if config["task"]["mode"] == "audit":
        return None
    output = config["output"]
    stamp = output["version"] or output["date"].replace("-", "")
    extension = "md" if output["format"] == "markdown" else output["format"]
    name = f"{config['project']['name']}_{output['report_label']}_{stamp}"
    if config["task"]["mode"] == "outline":
        name += "_outline"
        extension = "md"
    return Path(output["directory"]) / f"{name}.{extension}"
