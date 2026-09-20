#!/usr/bin/env python3
"""Resolve a report task into portable module contracts; does not write the report."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from portable_io import configure_utf8

from report_config import AGENTS, DEFAULTS, MODES, load_config, output_path


MODULES = {
    "inventory": {"reference": "references/evidence-writing.md", "script": "inventory_project.py", "input": "project files", "output": "inventory and source-backed statements"},
    "outline": {"reference": "references/report-structure.md", "script": None, "input": "requirements and source-backed statements", "output": "scoped outline"},
    "narrative": {"reference": "references/technical-narrative.md", "script": None, "input": "outline and project sources", "output": "report content"},
    "data": {"reference": "references/experimental-data.md", "script": "inspect_experiment_data.py", "input": "actual measurements", "output": "statistics with sample limits"},
    "visuals": {"reference": "references/visual-docx-qa.md", "script": None, "input": "project images and relationships", "output": "referenced figures and captions"},
    "document": {"reference": "references/docx-iteration-safety.md", "script": None, "input": "content and document settings", "output": "requested file format"},
    "polish": {"reference": "vendor/humanizer-zh/SKILL.md", "script": None, "input": "editable prose", "output": "edited prose with technical content preserved"},
    "appendix": {"reference": "references/exploded-view-and-appendix.md", "script": "appendix_images.py", "input": "document and referenced image manifest", "output": "document with image appendix"},
    "audit": {"reference": "references/docx-iteration-safety.md", "script": "audit_docx.py", "input": "final or existing document", "output": "structural findings"},
    "render": {"reference": "references/visual-docx-qa.md", "script": None, "input": "paginated document", "output": "rendered pages and visual findings"},
}
MODE_MODULES = {
    "create": ["inventory", "outline", "data", "narrative", "visuals", "polish", "document", "appendix", "audit", "render"],
    "revise": ["audit", "inventory", "data", "narrative", "visuals", "polish", "document", "appendix", "audit", "render"],
    "audit": ["audit", "render"],
    "outline": ["inventory", "outline"],
    "visuals": ["audit", "visuals", "document", "appendix", "audit", "render"],
}


def build_plan(config: dict) -> dict:
    mode = config["task"]["mode"]
    fmt = config["output"]["format"]
    if mode == "audit":
        suffix = Path(config["task"]["previous"]).suffix.lower()
        fmt = {".docx": "docx", ".pdf": "pdf", ".md": "markdown"}.get(suffix, "other")
    if mode == "outline":
        fmt = "markdown"
    target = output_path(config)
    blockers, warnings, steps = [], [], []
    if target is not None and target.exists():
        blockers.append(f"Output exists; choose another date/version/directory: {target}")
    caps = config["runtime"]["capabilities"]
    for index, name in enumerate(MODE_MODULES[mode]):
        entry = dict(MODULES[name], id=name, status="planned")
        step_format = fmt
        if name == "audit" and index == 0 and config["task"]["previous"]:
            suffix = Path(config["task"]["previous"]).suffix.lower()
            step_format = {".docx": "docx", ".pdf": "pdf", ".md": "markdown"}.get(suffix, "other")
        if name in {"audit", "document", "render", "appendix"}:
            entry["format"] = step_format
        setting = config["modules"].get(name, True)
        if setting is False:
            entry.update(status="skipped", reason="disabled in config")
        elif name in {"data", "visuals", "appendix"} and setting == "auto":
            entry.update(status="conditional", reason="run only for relevant project material")
        if name == "appendix" and fmt != "docx":
            entry["script"] = None
            entry["reason"] = "use the target format's native image/caption support"
        if name == "polish" and not config["task"]["language"].lower().startswith("zh"):
            entry["reference"] = "references/technical-narrative.md"
            entry["reason"] = "use target-language editing; Chinese humanizer is not applicable"
        if name == "document" and fmt != "markdown":
            if caps["document_writer"] is False:
                entry.update(status="blocked", reason="requested format requires a document writer")
                blockers.append(entry["reason"])
            elif caps["document_writer"] == "auto":
                entry.update(status="needs-capability-check", reason="Agent must verify its writer/export tool")
        if name == "audit" and step_format != "docx":
            entry["script"] = None
            entry["reason"] = "audit the requested format; do not pass it to the DOCX checker"
        if name == "render":
            policy = config["quality"]["render"]
            if fmt == "markdown":
                entry.update(status="not-applicable", reason="Markdown has no fixed page numbering")
            elif policy == "skip":
                entry.update(status="skipped", reason="visual rendering explicitly skipped")
            elif caps["renderer"] is False:
                entry.update(status="blocked" if policy == "required" else "unavailable", reason="renderer unavailable; visual quality unverified")
                (blockers if policy == "required" else warnings).append(entry["reason"])
            else:
                entry.update(status="needs-capability-check" if caps["renderer"] == "auto" else "planned", reason="rendering and visual inspection must actually run before claiming completion")
        steps.append(entry)
    if config["runtime"]["offline"]:
        warnings.append("Offline: use local project files and bundled references; no downloads or online lookup")
    if mode in {"revise", "visuals"} and config["document"]["revision_history"]:
        warnings.append("Append a revision entry; preserve earlier entries and compare unchanged content")
    return {
        "schema_version": 1, "status": "blocked" if blockers else "planned",
        "config": config, "target": str(target) if target else None,
        "effective_format": fmt, "modules": steps, "blockers": blockers, "warnings": warnings,
        "extensions": config["extensions"],
        "execution": "Agent executes module contracts using available tools; this plan alone is not a completed report",
    }


def main() -> int:
    configure_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--template", action="store_true")
    parser.add_argument("--project-name")
    parser.add_argument("--project-root")
    parser.add_argument("--mode", choices=sorted(MODES))
    parser.add_argument("--agent", choices=sorted(AGENTS))
    parser.add_argument("--format", choices=("docx", "markdown", "pdf"))
    parser.add_argument("--output", type=Path, help="Optional new JSON file for the plan/template")
    args = parser.parse_args()
    try:
        if args.template:
            result = copy.deepcopy(DEFAULTS)
            result["project"]["name"] = "项目名称"
        else:
            overrides = {}
            for group, field, value in (("project", "name", args.project_name), ("project", "root", args.project_root), ("task", "mode", args.mode), ("runtime", "agent", args.agent), ("output", "format", args.format)):
                if value is not None:
                    overrides.setdefault(group, {})[field] = value
            result = build_plan(load_config(args.config, overrides))
        content = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(content + "\n")
        else:
            print(content)
        return 1 if result.get("status") == "blocked" else 0
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "invalid", "errors": [str(error)]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
