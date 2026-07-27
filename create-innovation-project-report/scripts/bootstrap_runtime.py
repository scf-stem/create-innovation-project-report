#!/usr/bin/env python3
"""Detect and, when needed, install Python dependencies in an isolated cache."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import venv
from pathlib import Path


MIN_PYTHON = (3, 9)
PACKAGE_MAP = {
    "PIL": "Pillow",
    "docx": "python-docx",
    "yaml": "PyYAML",
}
SKILL_DEPENDENCIES = {
    "humanizer-zh": Path("vendor") / "humanizer-zh",
}
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MANAGED_MARKER = ".managed-by-create-innovation-project-report"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    parser.add_argument("--check-only", action="store_true", help="Do not install missing packages")
    parser.add_argument(
        "--agent-skills-root",
        type=Path,
        help="Agent skills directory. Defaults to the current skill's parent when named 'skills'.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def imported_modules(scripts_dir: Path) -> set[str]:
    modules: set[str] = set()
    for path in scripts_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".", 1)[0])
    return modules


def stdlib_module_names() -> set[str]:
    known = set(getattr(sys, "stdlib_module_names", ()))
    if known:
        return known
    known.update(sys.builtin_module_names)
    stdlib_path = Path(sysconfig.get_paths()["stdlib"])
    for path in stdlib_path.iterdir():
        if path.name in {"site-packages", "dist-packages", "__pycache__"}:
            continue
        if path.is_dir() and (path / "__init__.py").exists():
            known.add(path.name)
        elif path.suffix in {".py", ".so"}:
            known.add(path.stem.split(".", 1)[0])
    dynamic_paths = [stdlib_path / "lib-dynload"]
    destination_shared = sysconfig.get_config_var("DESTSHARED")
    if destination_shared:
        dynamic_paths.append(Path(destination_shared))
    for directory in dynamic_paths:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.suffix in {".so", ".pyd", ".dll"}:
                known.add(path.name.split(".", 1)[0])
    return known


def third_party_modules(skill_root: Path) -> list[str]:
    scripts_dir = skill_root / "scripts"
    local_modules = {path.stem for path in scripts_dir.glob("*.py")}
    stdlib = stdlib_module_names()
    stdlib.update({"__future__"})
    return sorted(imported_modules(scripts_dir) - local_modules - stdlib)


def missing_modules(modules: list[str], python: Path | None = None) -> list[str]:
    if python is None or python.resolve() == Path(sys.executable).resolve():
        return [module for module in modules if importlib.util.find_spec(module) is None]
    code = (
        "import importlib.util,json,sys;"
        "mods=json.loads(sys.argv[1]);"
        "print(json.dumps([m for m in mods if importlib.util.find_spec(m) is None]))"
    )
    completed = subprocess.run(
        [str(python), "-c", code, json.dumps(modules)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def cache_root() -> Path:
    override = os.environ.get("CODEX_SKILL_CACHE")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "codex-skills" / "create-innovation-project-report"


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def install_missing(modules: list[str]) -> Path:
    target = cache_root() / "venv"
    python = venv_python(target)
    if not python.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=False).create(target)
    packages = [PACKAGE_MAP.get(module, module) for module in modules]
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
            *packages,
        ],
        check=True,
    )
    remaining = missing_modules(modules, python)
    if remaining:
        raise RuntimeError("Dependencies remain unavailable: " + ", ".join(remaining))
    return python


def skill_name(skill_file: Path) -> str:
    if not skill_file.is_file():
        return ""
    match = FRONTMATTER_RE.match(skill_file.read_text(encoding="utf-8"))
    if not match:
        return ""
    for line in match.group(1).splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


def validate_skill_dependency(skill_dir: Path, expected_name: str) -> list[str]:
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    actual_name = skill_name(skill_file)
    if actual_name != expected_name:
        errors.append(
            f"Expected skill name {expected_name!r}, found {actual_name!r} in {skill_file}"
        )
        return errors

    text = skill_file.read_text(encoding="utf-8")
    for target in LINK_RE.findall(text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        linked_path = (skill_dir / target.split("#", 1)[0]).resolve()
        if not linked_path.exists():
            errors.append(f"Bundled skill link is missing: {target}")
    return errors


def infer_agent_skills_root(skill_root: Path, override: Path | None) -> Path | None:
    if override is not None:
        return override.expanduser().resolve()
    env_override = os.environ.get("AGENT_SKILLS_ROOT")
    if env_override:
        return Path(env_override).expanduser().resolve()
    parent = skill_root.parent
    if parent.name == "skills":
        return parent
    return None


def install_bundled_skill(
    source: Path,
    destination: Path,
    expected_name: str,
) -> tuple[bool, str | None]:
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{expected_name}-", dir=str(destination.parent))
        )
        shutil.rmtree(temporary)
        shutil.copytree(source, temporary)
        (temporary / MANAGED_MARKER).write_text(
            "Installed from the bundled dependency in create-innovation-project-report.\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    except FileExistsError:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
    except OSError as error:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        return False, str(error)

    errors = validate_skill_dependency(destination, expected_name)
    if errors:
        return False, "; ".join(errors)
    return True, None


def provision_skill_dependencies(
    skill_root: Path,
    check_only: bool,
    agent_skills_root: Path | None,
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    target_root = infer_agent_skills_root(skill_root, agent_skills_root)

    for name, relative_source in SKILL_DEPENDENCIES.items():
        source = skill_root / relative_source
        source_errors = validate_skill_dependency(source, name)
        dependency = {
            "name": name,
            "bundled_path": str(source),
            "target_skills_root": str(target_root) if target_root else None,
            "installed_now": False,
            "usable": not source_errors,
            "errors": source_errors,
            "warnings": [],
        }
        if source_errors:
            dependency.update({"status": "invalid", "mode": "unavailable", "path": None})
            result[name] = dependency
            continue

        if target_root is None:
            dependency.update(
                {
                    "status": "ready",
                    "mode": "bundled",
                    "path": str(source),
                }
            )
            result[name] = dependency
            continue

        destination = target_root / name
        installed_errors = validate_skill_dependency(destination, name)
        if not installed_errors:
            dependency.update(
                {
                    "status": "ready",
                    "mode": "installed",
                    "path": str(destination),
                }
            )
            result[name] = dependency
            continue

        if destination.exists():
            dependency["warnings"].append(
                "An incomplete or incompatible skill already exists at the install target; "
                "the bundled copy will be used without overwriting it."
            )
            dependency.update(
                {
                    "status": "ready",
                    "mode": "bundled",
                    "path": str(source),
                }
            )
            result[name] = dependency
            continue

        if check_only:
            dependency.update(
                {
                    "status": "ready",
                    "mode": "bundled",
                    "path": str(source),
                    "install_pending": True,
                }
            )
            result[name] = dependency
            continue

        installed, install_error = install_bundled_skill(source, destination, name)
        if installed:
            dependency.update(
                {
                    "status": "ready",
                    "mode": "installed",
                    "path": str(destination),
                    "installed_now": True,
                }
            )
        else:
            dependency["warnings"].append(
                "Automatic skill installation failed; using the bundled copy directly."
            )
            if install_error:
                dependency["warnings"].append(install_error)
            dependency.update(
                {
                    "status": "ready",
                    "mode": "bundled",
                    "path": str(source),
                }
            )
        result[name] = dependency

    return result


def capability_matrix() -> dict:
    return {
        "python": {
            "path": sys.executable,
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "minimum": ".".join(str(part) for part in MIN_PYTHON),
            "compatible": sys.version_info[:2] >= MIN_PYTHON,
        },
        "external_tools": {
            "libreoffice_or_soffice": shutil.which("soffice") or shutil.which("libreoffice"),
            "git": shutil.which("git"),
        },
        "notes": {
            "libreoffice_or_soffice": "Optional. Use structural DOCX checks when unavailable.",
            "git": "Optional. Only used when project history is relevant.",
        },
    }


def bootstrap(
    skill_root: Path,
    check_only: bool,
    agent_skills_root: Path | None = None,
) -> dict:
    root = skill_root.expanduser().resolve()
    capabilities = capability_matrix()
    if not capabilities["python"]["compatible"]:
        return {
            "status": "incompatible",
            "skill_root": str(root),
            "errors": [f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required."],
            "capabilities": capabilities,
        }

    third_party = third_party_modules(root)
    missing = missing_modules(third_party)
    selected_python = Path(sys.executable)
    installed = []
    if missing and not check_only:
        selected_python = install_missing(missing)
        installed = [PACKAGE_MAP.get(module, module) for module in missing]
        missing = missing_modules(third_party, selected_python)

    skill_dependencies = provision_skill_dependencies(
        root,
        check_only=check_only,
        agent_skills_root=agent_skills_root,
    )
    skill_dependency_errors = [
        error
        for dependency in skill_dependencies.values()
        for error in dependency["errors"]
    ]
    status = (
        "ready"
        if not missing and not skill_dependency_errors
        else "dependencies-missing"
    )
    return {
        "status": status,
        "skill_root": str(root),
        "python": str(selected_python),
        "third_party_modules": third_party,
        "missing_modules": missing,
        "installed_packages": installed,
        "skill_dependencies": skill_dependencies,
        "installed_skill_dependencies": [
            name
            for name, dependency in skill_dependencies.items()
            if dependency["installed_now"]
        ],
        "core_is_standard_library_only": not third_party,
        "capabilities": capabilities,
    }


def main() -> int:
    args = parse_args()
    result = bootstrap(
        args.skill_root,
        args.check_only,
        agent_skills_root=args.agent_skills_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"状态: {result['status']}")
        print(f"Python: {result.get('python', sys.executable)}")
        if result.get("installed_packages"):
            print("已安装: " + ", ".join(result["installed_packages"]))
        if result.get("missing_modules"):
            print("缺少模块: " + ", ".join(result["missing_modules"]))
        for name, dependency in result.get("skill_dependencies", {}).items():
            print(
                f"Skill 依赖 {name}: {dependency['mode']} "
                f"({dependency.get('path') or '不可用'})"
            )
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
