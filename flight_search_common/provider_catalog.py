from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = WORKSPACE_ROOT / "config" / "provider_catalog.yaml"


def _normalize_lookup(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _entry_aliases(key: str, entry: dict[str, Any]) -> list[str]:
    aliases = [key, entry.get("label", ""), entry.get("carrier_code", "")]
    aliases.extend(entry.get("aliases") or [])
    return [str(alias) for alias in aliases if str(alias or "").strip()]


@dataclass(frozen=True)
class ProviderCatalog:
    path: Path
    airlines: dict[str, dict[str, Any]]
    award_programs: dict[str, dict[str, Any]]
    award_web: dict[str, dict[str, Any]]

    def airline_code(self, value: Any) -> str:
        return self._carrier_code_for(value, self.airlines)

    def award_program_code(self, value: Any) -> str:
        return self._carrier_code_for(value, self.award_programs)

    def award_web_label(self, source_name: Any) -> str:
        key = str(source_name or "").strip().lower()
        entry = self.award_web.get(key)
        if entry and entry.get("label"):
            return str(entry["label"])
        program = self.award_programs.get(key)
        if program and program.get("label"):
            return f"{program['label']} Web"
        return f"{str(source_name or 'web').strip().title()} Web"

    def airline_logo_files(self) -> dict[str, Path]:
        logos: dict[str, Path] = {}
        for entry in self.airlines.values():
            code = str(entry.get("carrier_code") or "").strip().upper()
            logo_path = entry.get("logo_path")
            if code and logo_path:
                path = Path(str(logo_path))
                logos[code] = path if path.is_absolute() else WORKSPACE_ROOT / path
        return logos

    def one_way_only_round_trip_sources(self) -> set[str]:
        sources: set[str] = set()
        for key, entry in self.award_web.items():
            trip_types = {str(value).lower() for value in entry.get("supported_trip_types") or []}
            round_trip_mode = str(entry.get("round_trip_mode") or "").lower()
            if round_trip_mode == "sum_one_way" or "round-trip" not in trip_types:
                sources.add(key)
                source_name = str(entry.get("source_name") or "").strip().lower()
                if source_name:
                    sources.add(source_name)
        return sources

    def award_web_provider_keys(self) -> list[str]:
        return sorted(self.award_web)

    def award_web_provider_config(self, key: str) -> dict[str, Any]:
        normalized = str(key or "").strip().lower()
        if normalized not in self.award_web:
            raise KeyError(f"Unknown award-web provider: {key}")
        return dict(self.award_web[normalized])

    def _carrier_code_for(self, value: Any, entries: dict[str, dict[str, Any]]) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = _normalize_lookup(text)
        for key, entry in entries.items():
            if normalized == _normalize_lookup(key):
                return str(entry.get("carrier_code") or "").strip().upper()
            for alias in _entry_aliases(key, entry):
                if normalized == _normalize_lookup(alias):
                    return str(entry.get("carrier_code") or "").strip().upper()

        for key, entry in entries.items():
            for alias in _entry_aliases(key, entry):
                alias_normalized = _normalize_lookup(alias)
                if len(alias_normalized) >= 4 and alias_normalized in normalized:
                    return str(entry.get("carrier_code") or "").strip().upper()
        return ""


@lru_cache(maxsize=8)
def _load_provider_catalog(path_value: str) -> ProviderCatalog:
    path = Path(path_value)
    with path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return ProviderCatalog(
        path=path,
        airlines=dict(payload.get("airlines") or {}),
        award_programs=dict(payload.get("award_programs") or {}),
        award_web=dict(payload.get("award_web") or {}),
    )


def load_provider_catalog(path: str | Path | None = None) -> ProviderCatalog:
    catalog_path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    return _load_provider_catalog(str(catalog_path.resolve()))
