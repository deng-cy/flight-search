from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from flight_search_common.provider_catalog import load_provider_catalog


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG_PATH = WORKSPACE_ROOT / "config" / "provider_catalog.yaml"


@dataclass(frozen=True)
class AwardWebProvider:
    key: str
    label: str
    carrier_code: str
    module: str
    run_function: str
    supported_trip_types: tuple[str, ...]
    round_trip_mode: str
    evidence_outputs: tuple[str, ...]
    confidence: str

    def supports_trip_type(self, trip_type: str) -> bool:
        return trip_type in self.supported_trip_types

    def run_callable(self) -> Callable[..., dict[str, Any]]:
        module = importlib.import_module(self.module)
        function = getattr(module, self.run_function)
        if not callable(function):
            raise TypeError(f"{self.module}.{self.run_function} is not callable")
        return function

    def run_pipeline(self, **kwargs: Any) -> dict[str, Any]:
        trip_type = str(kwargs.get("trip_type") or "one-way")
        if not self.supports_trip_type(trip_type):
            supported = ", ".join(self.supported_trip_types)
            raise ValueError(f"{self.label} award web searches support {supported}; got {trip_type}.")
        return self.run_callable()(**kwargs)


def provider_from_config(key: str, config: dict[str, Any]) -> AwardWebProvider:
    return AwardWebProvider(
        key=key,
        label=str(config.get("label") or key.title()),
        carrier_code=str(config.get("carrier_code") or ""),
        module=str(config.get("module") or ""),
        run_function=str(config.get("run_function") or "run_pipeline"),
        supported_trip_types=tuple(str(value) for value in config.get("supported_trip_types") or ["one-way"]),
        round_trip_mode=str(config.get("round_trip_mode") or "one_way"),
        evidence_outputs=tuple(str(value) for value in config.get("evidence_outputs") or []),
        confidence=str(config.get("confidence") or ""),
    )


def available_provider_keys(catalog_path: Path = DEFAULT_CATALOG_PATH) -> list[str]:
    catalog = load_provider_catalog(catalog_path)
    return catalog.award_web_provider_keys()


def get_provider(key: str, catalog_path: Path = DEFAULT_CATALOG_PATH) -> AwardWebProvider:
    normalized = str(key or "").strip().lower()
    catalog = load_provider_catalog(catalog_path)
    config = catalog.award_web_provider_config(normalized)
    return provider_from_config(normalized, config)


def registered_providers(catalog_path: Path = DEFAULT_CATALOG_PATH) -> dict[str, AwardWebProvider]:
    return {
        key: get_provider(key, catalog_path=catalog_path)
        for key in available_provider_keys(catalog_path)
    }


def run_provider(provider_key: str, **kwargs: Any) -> dict[str, Any]:
    provider = get_provider(provider_key)
    return provider.run_pipeline(**kwargs)
