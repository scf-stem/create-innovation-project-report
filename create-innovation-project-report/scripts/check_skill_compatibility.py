#!/usr/bin/env python3
"""Check skill portability, metadata, dependencies, and name collisions."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

from bootstrap_runtime import bootstrap, imported_modules, stdlib_module_names


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ABSOLUTE_PATH_RE = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    parser.add_argument("--scan-root", type=Path, action="append", default=[])
    parser.add_argument("--skip-script-help", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def default_scan_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".codex" / "skills",
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".codex" / "plugins" / "cache",
    ]
    return [path for path in candidates if path.is_dir()]


def scan_skill_names(roots: list[Path]) -> tuple[dict[str, list[str]], int]:
    names: dict[str, list[str]] = {}
    scanned = 0
    seen_paths: set[Path] = set()
    for root in roots:
        resolved_root = root.resolve()
        for skill_file in root.rglob("SKILL.md"):
            resolved = skill_file.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                relative_parts = resolved.relative_to(resolved_root).parts
            except ValueError:
                relative_parts = ()
            if "vendor" in relative_parts[:-1]:
                continue
            metadata = parse_frontmatter(skill_file)
            name = metadata.get("name")
            if name:
                names.setdefault(name, []).append(str(skill_file.parent.resolve()))
            scanned += 1
    return names, scanned


def check_references(skill_root: Path) -> list[str]:
    errors = []
    for markdown in [skill_root / "SKILL.md", *(skill_root / "references").glob("*.md")]:
        text = markdown.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target_path = (markdown.parent / target.split("#", 1)[0]).resolve()
            if not target_path.exists():
                errors.append(f"Broken link in {markdown.name}: {target}")
    return errors


def check_agent_metadata(skill_root: Path, skill_name: str) -> list[str]:
    errors = []
    path = skill_root / "agents" / "openai.yaml"
    if not path.is_file():
        return ["agents/openai.yaml is missing"]
    text = path.read_text(encoding="utf-8")
    for field in ("display_name", "short_description", "default_prompt"):
        if not re.search(rf"^\s*{field}:\s*\"[^\"]+\"\s*$", text, re.M):
            errors.append(f"agents/openai.yaml has invalid or unquoted {field}")
    if f"${skill_name}" not in text:
        errors.append("agents/openai.yaml default_prompt does not mention the skill")
    return errors


def check_script_imports(skill_root: Path) -> tuple[list[str], list[str]]:
    scripts_dir = skill_root / "scripts"
    local = {path.stem for path in scripts_dir.glob("*.py")}
    stdlib = stdlib_module_names()
    stdlib.add("__future__")
    third_party = sorted(imported_modules(scripts_dir) - local - stdlib)
    syntax_errors = []
    for path in scripts_dir.glob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            syntax_errors.append(f"{path.name}: {error}")
    return third_party, syntax_errors


def run_help_checks(skill_root: Path) -> list[str]:
    failures = []
    for script in sorted((skill_root / "scripts").glob("*.py")):
        if script.name == "image_utils.py":
            continue
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=skill_root,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            failures.append(f"{script.name}: {completed.stderr.strip()[:300]}")
    return failures


def check_portability(skill_root: Path) -> list[str]:
    warnings = []
    for path in [skill_root / "SKILL.md", *(skill_root / "references").glob("*.md")]:
        text = path.read_text(encoding="utf-8")
        if ABSOLUTE_PATH_RE.search(text):
            warnings.append(f"User-specific absolute path found in {path.name}")
    return warnings


def check(skill_root: Path, scan_roots: list[Path], run_help: bool) -> dict:
    root = skill_root.expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        return {"status": "incompatible", "errors": ["SKILL.md is missing"], "warnings": []}

    metadata = parse_frontmatter(skill_file)
    name = metadata.get("name", "")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        errors.append("Skill name must use lowercase letters, digits, and hyphens")
    if set(metadata) != {"name", "description"}:
        errors.append("SKILL.md frontmatter must contain only name and description")
    if not metadata.get("description"):
        errors.append("Skill description is missing")
    if root.name != name:
        errors.append("Skill directory name does not match frontmatter name")
    if len(skill_file.read_text(encoding="utf-8").splitlines()) >= 500:
        errors.append("SKILL.md must remain below 500 lines")

    errors.extend(check_references(root))
    errors.extend(check_agent_metadata(root, name))
    third_party, syntax_errors = check_script_imports(root)
    errors.extend(syntax_errors)
    if run_help:
        errors.extend(run_help_checks(root))
    warnings.extend(check_portability(root))

    runtime = bootstrap(root, check_only=True)
    if runtime["status"] != "ready":
        errors.append("Runtime bootstrap check failed")

    roots = scan_roots or default_scan_roots()
    names, scanned = scan_skill_names(roots)
    current_paths = [Path(path).resolve() for path in names.get(name, [])]
    collisions = [str(path) for path in current_paths if path != root]
    if collisions:
        errors.append("Skill name collision: " + "; ".join(collisions))

    return {
        "status": "compatible" if not errors else "incompatible",
        "skill_root": str(root),
        "skill_name": name,
        "agent_skill_roots_scanned": [str(path.resolve()) for path in roots],
        "agent_skills_scanned": scanned,
        "name_collisions": collisions,
        "third_party_modules": third_party,
        "core_is_standard_library_only": not third_party,
        "skill_dependencies": runtime.get("skill_dependencies", {}),
        "runtime": runtime,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    args = parse_args()
    result = check(args.skill_root, args.scan_root, not args.skip_script_help)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"兼容性: {result['status']}")
        print(f"扫描 Agent Skills: {result.get('agent_skills_scanned', 0)}")
        print("仅使用标准库: " + ("是" if result.get("core_is_standard_library_only") else "否"))
        for name, dependency in result.get("skill_dependencies", {}).items():
            print(f"Skill 依赖 {name}: {dependency['mode']}")
        for error in result.get("errors", []):
            print(f"错误: {error}")
        for warning in result.get("warnings", []):
            print(f"警告: {warning}")
    return 0 if result["status"] == "compatible" else 1


if __name__ == "__main__":
    raise SystemExit(main())
