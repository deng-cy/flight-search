#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import getpass
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional


REQUIRED_IMPORTS = {
    "fastapi": "seat_aero/requirements.txt",
    "httpx": "seat_aero/requirements.txt",
    "yaml": "shared PyYAML requirement",
    "uvicorn": "seat_aero/requirements.txt",
    "fli": "cash/requirements.txt (flights package)",
    "click": "cash/requirements.txt",
    "playwright": "award_web/requirements.txt",
}


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_preferences_subset(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return parse_preferences_subset(path)

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def parse_preferences_subset(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {"points": {"programs": {}}, "ranking": {"time_penalties": {}}}
    if not path.exists():
        return data

    top = ""
    in_programs = False
    current_program = ""
    current_time_group = ""
    current_rule: Optional[dict[str, Any]] = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if "#" in stripped and not stripped.startswith(("'", '"')):
            stripped = stripped.split("#", 1)[0].rstrip()
        if not stripped:
            continue

        if indent == 0 and stripped.endswith(":"):
            top = stripped[:-1]
            in_programs = False
            current_program = ""
            current_time_group = ""
            current_rule = None
            continue

        if top == "points":
            if indent == 2 and stripped == "programs:":
                in_programs = True
                continue
            if indent == 2 and ":" in stripped:
                key, value = stripped.split(":", 1)
                if key == "default_cents_per_point":
                    data["points"]["default_cents_per_point"] = parse_scalar(value)
                continue
            if in_programs and indent == 4 and stripped.endswith(":"):
                current_program = stripped[:-1]
                data["points"]["programs"].setdefault(current_program, {})
                continue
            if in_programs and current_program and indent == 6 and ":" in stripped:
                key, value = stripped.split(":", 1)
                if key in {"label", "cents_per_point"}:
                    data["points"]["programs"][current_program][key] = parse_scalar(value)
                continue

        if top == "ranking":
            if indent == 2 and ":" in stripped and not stripped.endswith(":"):
                key, value = stripped.split(":", 1)
                if key == "duration_penalty_usd_per_hour":
                    data["ranking"][key] = parse_scalar(value)
                continue
            if indent == 4 and stripped.endswith(":"):
                current_time_group = stripped[:-1]
                data["ranking"]["time_penalties"].setdefault(current_time_group, [])
                current_rule = None
                continue
            if indent == 6 and stripped.startswith("- ") and current_time_group:
                current_rule = {}
                data["ranking"]["time_penalties"][current_time_group].append(current_rule)
                rest = stripped[2:].strip()
                if rest and ":" in rest:
                    key, value = rest.split(":", 1)
                    current_rule[key] = parse_scalar(value)
                continue
            if indent == 8 and current_rule is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_rule[key] = parse_scalar(value)

    return data


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        result = deepcopy(base)
        for key, value in override.items():
            result[key] = deep_merge(result[key], value) if key in result else deep_merge({}, value)
        return result
    return deepcopy(override)


def scalar_yaml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text or any(char in text for char in [":", "#", '"']) or text.lower() in {"true", "false", "null"}:
        return '"' + text.replace('"', '\\"') + '"'
    return text


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key in sorted(value):
            item = value[key]
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {scalar_yaml(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{pad}-")
                lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}- {scalar_yaml(item)}")
        return lines
    return [f"{pad}{scalar_yaml(value)}"]


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(yaml_lines(data)) + "\n", encoding="utf-8")


def prune_empty(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for key in list(value):
        child = value[key]
        if isinstance(child, dict) and prune_empty(child):
            del value[key]
    return not value


def values_equal(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return left == right


def set_path(data: dict[str, Any], keys: Iterable[str], value: Any) -> None:
    current = data
    key_list = list(keys)
    for key in key_list[:-1]:
        next_value = current.setdefault(key, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[key_list[-1]] = value


def remove_path(data: dict[str, Any], keys: Iterable[str]) -> None:
    current = data
    parents: list[tuple[dict[str, Any], str]] = []
    key_list = list(keys)
    for key in key_list[:-1]:
        value = current.get(key)
        if not isinstance(value, dict):
            return
        parents.append((current, key))
        current = value
    current.pop(key_list[-1], None)
    for parent, key in reversed(parents):
        value = parent.get(key)
        if isinstance(value, dict) and not value:
            parent.pop(key, None)


def store_override(local: dict[str, Any], base: dict[str, Any], keys: list[str], value: Any) -> None:
    base_value: Any = base
    for key in keys:
        if not isinstance(base_value, dict) or key not in base_value:
            base_value = None
            break
        base_value = base_value[key]
    if values_equal(base_value, value):
        remove_path(local, keys)
    else:
        set_path(local, keys, value)


def dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_dotenv(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(values)
    output: list[str] = []
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            output.append(raw_line)
            continue
        key = raw_line.split("=", 1)[0].strip()
        if key in pending:
            output.append(f"{key}={pending.pop(key)}")
        else:
            output.append(raw_line)
    for key, value in pending.items():
        output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def prompt_secret(prompt: str, existing: str = "") -> str:
    if existing:
        value = getpass.getpass(f"{prompt} [leave blank to keep existing]: ").strip()
        return value or existing
    while True:
        value = getpass.getpass(f"{prompt}: ").strip()
        if value:
            return value
        print("A Seats.aero API key is required for live award searches.")


def prompt_yes_no(prompt: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.")


def prompt_float(prompt: str, default: Any) -> float:
    while True:
        answer = input(f"{prompt} [{default}]: ").strip()
        value = default if answer == "" else answer
        try:
            return float(value)
        except (TypeError, ValueError):
            print("Please enter a number.")


def setup_env(env_path: Path, example_path: Path, api_key: Optional[str]) -> None:
    existing = dotenv_values(env_path)
    example = dotenv_values(example_path)
    resolved_key = api_key.strip() if api_key else prompt_secret("Seats.aero API key", existing.get("SEATS_AERO_API_KEY", ""))
    values = dict(example)
    values.update(existing)
    values["SEATS_AERO_API_KEY"] = resolved_key
    write_dotenv(env_path, values)
    print(f"Wrote local Seats.aero settings to {env_path}")


def prompt_point_preferences(base: dict[str, Any], effective: dict[str, Any], local: dict[str, Any]) -> None:
    points = effective.get("points", {})
    programs = points.get("programs", {})
    if not prompt_yes_no("Customize cents-per-point values?", False):
        return

    default_cpp = prompt_float("Default cents per point", points.get("default_cents_per_point", 2.0))
    store_override(local, base, ["points", "default_cents_per_point"], default_cpp)

    for program in sorted(programs):
        config = programs[program] or {}
        label = config.get("label", program)
        cpp = prompt_float(f"{label} ({program}) cents per point", config.get("cents_per_point", default_cpp))
        store_override(local, base, ["points", "programs", program, "cents_per_point"], cpp)


def prompt_penalty_preferences(base: dict[str, Any], effective: dict[str, Any], local: dict[str, Any]) -> None:
    ranking = effective.get("ranking", {})
    if not prompt_yes_no("Customize duration or early/late timing penalties?", False):
        return

    duration = prompt_float("Duration penalty USD per travel hour", ranking.get("duration_penalty_usd_per_hour", 5))
    store_override(local, base, ["ranking", "duration_penalty_usd_per_hour"], duration)

    base_rules = base.get("ranking", {}).get("time_penalties", {})
    effective_rules = ranking.get("time_penalties", {})
    for group in ["departure", "arrival"]:
        rules = effective_rules.get(group, [])
        if not isinstance(rules, list):
            continue
        updated_rules = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            label = rule.get("label", "time penalty")
            start = rule.get("start", "")
            end = rule.get("end", "")
            penalty = prompt_float(f"{group} penalty for {label} ({start}-{end})", rule.get("penalty_usd", 0))
            updated = dict(rule)
            updated["penalty_usd"] = penalty
            updated_rules.append(updated)
        if values_equal(updated_rules, base_rules.get(group, [])):
            remove_path(local, ["ranking", "time_penalties", group])
        else:
            set_path(local, ["ranking", "time_penalties", group], updated_rules)


def configure_preferences(preferences_path: Path, local_path: Path, use_defaults: bool) -> None:
    base = load_preferences_subset(preferences_path)
    local = load_preferences_subset(local_path) if local_path.exists() else {}
    effective = deep_merge(base, local)

    if use_defaults:
        print("Keeping default scoring preferences.")
        return

    before = repr(local)
    prompt_point_preferences(base, effective, local)
    effective = deep_merge(base, local)
    prompt_penalty_preferences(base, effective, local)
    prune_empty(local)

    if repr(local) == before:
        print("No local scoring preference changes.")
        return
    if local:
        write_yaml(local_path, local)
        print(f"Wrote local scoring overrides to {local_path}")
    elif local_path.exists():
        local_path.unlink()
        print(f"Removed empty local scoring overrides from {local_path}")


def python_version(executable: str) -> Optional[tuple[int, int, int]]:
    try:
        output = subprocess.check_output(
            [executable, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    parts = output.split(".")
    if len(parts) != 3:
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def candidate_pythons(repo_root: Optional[Path] = None, include_venv: bool = True) -> list[str]:
    names = []
    if repo_root is not None and include_venv:
        names.append(str(venv_python(repo_root)))
    names.extend([sys.executable, "python3.13", "python3.12", "python3.11", "python3.10", "python3"])
    paths: list[str] = []
    for name in names:
        path = name if os.path.isabs(name) else shutil.which(name)
        if path and Path(path).exists() and path not in paths:
            paths.append(path)
    return paths


def best_python(repo_root: Optional[Path] = None, include_venv: bool = True) -> Optional[str]:
    for executable in candidate_pythons(repo_root, include_venv=include_venv):
        version = python_version(executable)
        if version and version >= (3, 10, 0):
            return executable
    return None


def missing_imports(executable: str) -> list[str]:
    code = "import importlib.util; import sys; missing=[m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]; print('\\n'.join(missing))"
    try:
        output = subprocess.check_output([executable, "-c", code, *REQUIRED_IMPORTS], text=True)
    except (OSError, subprocess.CalledProcessError):
        return list(REQUIRED_IMPORTS)
    return [line.strip() for line in output.splitlines() if line.strip()]


def run_command(command: list[str], cwd: Path) -> None:
    print("+ " + " ".join(shlex.quote(part) for part in command))
    subprocess.check_call(command, cwd=str(cwd))


def venv_python(repo_root: Path) -> Path:
    if os.name == "nt":
        return repo_root / ".venv" / "Scripts" / "python.exe"
    return repo_root / ".venv" / "bin" / "python"


def install_dependencies(repo_root: Path, python_executable: str, create_venv: bool) -> None:
    target_python = Path(python_executable)
    if create_venv:
        run_command([python_executable, "-m", "venv", ".venv"], repo_root)
        target_python = venv_python(repo_root)
    for requirements in ["seat_aero/requirements.txt", "cash/requirements.txt", "award_web/requirements.txt"]:
        run_command([str(target_python), "-m", "pip", "install", "-r", requirements], repo_root)
    run_command([str(target_python), "-m", "playwright", "install", "chromium"], repo_root)
    print(f"Python environment ready: {target_python}")


def check_python_environment(repo_root: Path, skip_dependencies: bool) -> None:
    project_python = venv_python(repo_root) if venv_python(repo_root).exists() else Path(sys.executable)
    version = python_version(str(project_python))
    version_ok = bool(version and version >= (3, 10, 0))
    missing = missing_imports(str(project_python)) if version else list(REQUIRED_IMPORTS)
    if version_ok and not missing:
        print(
            "Python environment already has required packages: "
            f"{project_python} ({version[0]}.{version[1]}.{version[2]})"
        )
        return

    if version:
        print(f"Project Python checked: {project_python} ({version[0]}.{version[1]}.{version[2]})")
    else:
        print(f"Project Python checked: {project_python} (not runnable)")
    if not version_ok:
        print("Python 3.10 or newer is required for the cash provider.")
    print("Missing Python packages:")
    for module in missing:
        print(f"- {module} ({REQUIRED_IMPORTS[module]})")
    if skip_dependencies:
        print("Skipped dependency installation.")
        return

    print("Dependency setup options:")
    print("1. Create/update local .venv and install everything there (default)")
    print("2. Install missing project requirements into the detected Python")
    print("3. Skip dependency installation")
    choice = input("Choose an option [1]: ").strip() or "1"
    if choice == "3":
        print("Skipped dependency installation.")
        return
    if choice == "2":
        if not version_ok:
            print("Cannot install into this Python because it is below 3.10.")
            return
        install_dependencies(repo_root, str(project_python), create_venv=False)
        return

    existing_venv = venv_python(repo_root)
    existing_venv_version = python_version(str(existing_venv)) if existing_venv.exists() else None
    if existing_venv_version and existing_venv_version >= (3, 10, 0):
        install_dependencies(repo_root, str(existing_venv), create_venv=False)
        return

    creator = best_python(repo_root, include_venv=False)
    if creator is None:
        print("No Python >=3.10 executable was found. Install Python 3.10+ before dependency setup.")
        return
    install_dependencies(repo_root, creator, create_venv=True)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up the Flight_search repository for local use.")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--api-key", default="", help="Seats.aero API key. If omitted, prompt securely.")
    parser.add_argument("--use-default-preferences", action="store_true", help="Do not prompt for local scoring overrides.")
    parser.add_argument("--skip-dependencies", action="store_true", help="Do not install Python packages or Playwright.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    setup_env(
        repo_root / "seat_aero" / ".env",
        repo_root / "seat_aero" / ".env.example",
        args.api_key or None,
    )
    configure_preferences(
        repo_root / "config" / "search_preferences.yaml",
        repo_root / "config" / "search_preferences.local.yaml",
        args.use_default_preferences,
    )
    check_python_environment(repo_root, args.skip_dependencies)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
