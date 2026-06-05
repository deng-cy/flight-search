from __future__ import annotations

from pathlib import Path
from typing import Any


def normalize_airport(value: str) -> str:
    return value.strip().upper()


def slug(value: str) -> str:
    return value.lower().replace(",", "_").replace(" ", "_")


def source_from_path(path: Path) -> str:
    return path.name.split("_", 1)[0]


def cents_to_amount(value: Any) -> float:
    return int(value or 0) / 100


def time_label(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    return timestamp[11:16]


def date_part(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    return timestamp[:10]


def is_next_day(departs_at: str | None, arrives_at: str | None) -> bool:
    return bool(departs_at and arrives_at and date_part(arrives_at) > date_part(departs_at))


def arrival_label(departs_at: str | None, arrives_at: str | None) -> str:
    label = time_label(arrives_at)
    if is_next_day(departs_at, arrives_at):
        label += " +1"
    return label


def money(amount: float | int | str | None, currency: str = "USD") -> str:
    if amount in (None, ""):
        return ""
    return f"{currency} {float(amount):,.2f}"


def points(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{int(value):,}"

