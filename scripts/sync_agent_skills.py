#!/usr/bin/env python3
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


SOURCE_DIR = "agent_skills"
TOOL_SKILL_DIRS = {
    "codex": Path(".codex/skills"),
    "claude": Path(".claude/skills"),
}
MARKER_NAME = ".agent_skill_source"
IGNORED_NAMES = {".DS_Store", "__pycache__", MARKER_NAME}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def skill_names(root: Path, names: list[str]) -> list[str]:
    if names:
        return names
    source_root = root / SOURCE_DIR
    if not source_root.exists():
        return []
    return sorted(path.name for path in source_root.iterdir() if path.is_dir())


def ignore_names(_: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED_NAMES or name.endswith(".pyc")}


def copy_skill(source: Path, destination: Path, *, marker: str | None = None) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing skill source: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, ignore=ignore_names)
    if marker:
        (destination / MARKER_NAME).write_text(marker + "\n", encoding="utf-8")


def sync_to_tools(root: Path, names: list[str]) -> None:
    selected = skill_names(root, names)
    for name in selected:
        source = root / SOURCE_DIR / name
        for tool, tool_root in TOOL_SKILL_DIRS.items():
            destination = root / tool_root / name
            copy_skill(source, destination, marker=f"Generated from {SOURCE_DIR}/{name}; sync with scripts/sync_agent_skills.py.")
            print(f"synced {SOURCE_DIR}/{name} -> {tool}:{tool_root / name}")


def sync_from_tool(root: Path, tool: str, name: str) -> None:
    if tool not in TOOL_SKILL_DIRS:
        raise ValueError(f"Unknown tool {tool!r}; expected one of {', '.join(sorted(TOOL_SKILL_DIRS))}")
    source = root / TOOL_SKILL_DIRS[tool] / name
    destination = root / SOURCE_DIR / name
    copy_skill(source, destination)
    print(f"synced {tool}:{TOOL_SKILL_DIRS[tool] / name} -> {SOURCE_DIR}/{name}")


def compare_dirs(left: Path, right: Path) -> list[str]:
    if not left.exists():
        return [f"missing {left}"]
    if not right.exists():
        return [f"missing {right}"]

    comparison = filecmp.dircmp(left, right, ignore=sorted(IGNORED_NAMES))
    differences: list[str] = []
    for name in comparison.left_only:
        if name not in IGNORED_NAMES:
            differences.append(f"only in {left}: {name}")
    for name in comparison.right_only:
        if name not in IGNORED_NAMES:
            differences.append(f"only in {right}: {name}")
    for name in comparison.diff_files:
        differences.append(f"different: {left / name} != {right / name}")
    for name, child in comparison.subdirs.items():
        differences.extend(compare_dirs(left / name, right / name))
    return differences


def check_sync(root: Path, names: list[str]) -> int:
    selected = skill_names(root, names)
    differences: list[str] = []
    for name in selected:
        source = root / SOURCE_DIR / name
        for tool, tool_root in TOOL_SKILL_DIRS.items():
            differences.extend(compare_dirs(source, root / tool_root / name))
    if differences:
        for difference in differences:
            print(difference, file=sys.stderr)
        return 1
    print("agent skills are in sync")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync canonical agent skills into Codex and Claude skill directories.")
    parser.add_argument("skills", nargs="*", help="Skill names. Defaults to all skills in agent_skills/.")
    parser.add_argument("--root", type=Path, default=repo_root(), help="Repository root, mostly for tests.")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--to-tools", action="store_true", help="Copy canonical skills to .codex/skills and .claude/skills.")
    action.add_argument("--check", action="store_true", help="Verify tool skill copies match canonical skills.")
    action.add_argument("--from", dest="from_tool", choices=sorted(TOOL_SKILL_DIRS), help="Copy one tool skill back to canonical.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if args.from_tool:
        if len(args.skills) != 1:
            raise SystemExit("--from requires exactly one skill name")
        sync_from_tool(root, args.from_tool, args.skills[0])
        return 0
    if args.to_tools:
        sync_to_tools(root, args.skills)
        return 0
    return check_sync(root, args.skills)


if __name__ == "__main__":
    raise SystemExit(main())
