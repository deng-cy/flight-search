from __future__ import annotations

from typing import Any

from .providers.registry import (
    AwardWebProvider,
    available_provider_keys,
    get_provider,
    registered_providers,
    run_provider,
)


def run_pipeline(*, source_name: str = "delta", provider_key: str | None = None, **kwargs: Any) -> dict[str, Any]:
    key = (provider_key or source_name or "delta").strip().lower()
    return run_provider(key, **kwargs)


__all__ = [
    "AwardWebProvider",
    "available_provider_keys",
    "get_provider",
    "registered_providers",
    "run_pipeline",
    "run_provider",
]
