from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREFERENCES_PATH = WORKSPACE_ROOT / "config/search_preferences.yaml"


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = deepcopy(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else deep_merge({}, value)
        return merged
    return deepcopy(override)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        preferences = yaml.safe_load(handle)
    if not isinstance(preferences, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return preferences


def local_preferences_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.local{path.suffix}")


def is_default_preferences_path(path: Path) -> bool:
    try:
        return path.resolve() == DEFAULT_PREFERENCES_PATH.resolve()
    except OSError:
        return False


def load_preferences(path: Path, *, apply_local_overlay: bool | None = None) -> dict[str, Any]:
    preferences = load_yaml_mapping(path)
    should_apply_overlay = is_default_preferences_path(path) if apply_local_overlay is None else apply_local_overlay
    if not should_apply_overlay:
        return preferences

    local_path = local_preferences_path(path)
    if not local_path.exists():
        return preferences
    return deep_merge(preferences, load_yaml_mapping(local_path))
