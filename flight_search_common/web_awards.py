from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .formatting import slug
from .io import load_json


ONE_WAY_ONLY_ROUND_TRIP_SOURCES = {"southwest"}


def numeric(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def award_web_candidate_paths(
    workspace_root: Path,
    *,
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str,
) -> list[Path]:
    normalized_dir = workspace_root / "award_web" / "data" / "normalized"
    if not normalized_dir.exists():
        return []
    stem = f"*_{slug(origin)}_{slug(destination)}_{departure_date}_{cabin.replace('-', '_')}_one_way_web_awards.json"
    return sorted(normalized_dir.glob(stem))


def award_web_round_trip_candidate_paths(
    workspace_root: Path,
    *,
    origin: str,
    destination: str,
    departure_date: str,
    return_origin: str,
    return_destination: str,
    return_date: str,
    cabin: str,
) -> list[Path]:
    normalized_dir = workspace_root / "award_web" / "data" / "normalized"
    if not normalized_dir.exists():
        return []
    stem = (
        f"*_{slug(origin)}_{slug(destination)}_{departure_date}_"
        f"{slug(return_origin)}_{slug(return_destination)}_{return_date}_"
        f"{cabin.replace('-', '_')}_round_trip_web_awards.json"
    )
    return sorted(normalized_dir.glob(stem))


def load_web_award_rows(
    workspace_root: Path,
    *,
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str,
    paths: Iterable[Path] | None = None,
) -> list[dict[str, Any]]:
    candidate_paths = list(paths) if paths is not None else award_web_candidate_paths(
        workspace_root,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        cabin=cabin,
    )
    rows: list[dict[str, Any]] = []
    for path in candidate_paths:
        payload = load_json(path)
        if not isinstance(payload, list):
            continue
        rows.extend(
            adapt_web_award_row(row, evidence_source=path)
            for row in payload
            if isinstance(row, dict)
            and web_award_row_matches(
                row,
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                cabin=cabin,
            )
        )
    return sorted(
        deduplicate_award_rows(rows),
        key=lambda row: (
            numeric(row.get("score")),
            numeric(row.get("effective_usd")),
            numeric(row.get("duration_minutes")),
        ),
    )


def load_web_round_trip_award_rows(
    workspace_root: Path,
    *,
    origin: str,
    destination: str,
    departure_date: str,
    return_origin: str,
    return_destination: str,
    return_date: str,
    cabin: str,
    paths: Iterable[Path] | None = None,
) -> list[dict[str, Any]]:
    candidate_paths = list(paths) if paths is not None else award_web_round_trip_candidate_paths(
        workspace_root,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_origin=return_origin,
        return_destination=return_destination,
        return_date=return_date,
        cabin=cabin,
    )
    rows: list[dict[str, Any]] = []
    for path in candidate_paths:
        payload = load_json(path)
        if not isinstance(payload, list):
            continue
        rows.extend(
            adapt_web_award_row(row, evidence_source=path)
            for row in payload
            if isinstance(row, dict)
            and web_round_trip_row_matches(
                row,
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                return_origin=return_origin,
                return_destination=return_destination,
                return_date=return_date,
                cabin=cabin,
            )
        )
    return sorted(
        deduplicate_award_rows(rows),
        key=lambda row: (
            numeric(row.get("score")),
            numeric(row.get("effective_usd")),
            numeric(row.get("duration_minutes")),
        ),
    )


def web_award_row_matches(
    row: dict[str, Any],
    *,
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str,
) -> bool:
    return (
        str(row.get("origin", "")).upper() == origin.upper()
        and str(row.get("destination", "")).upper() == destination.upper()
        and str(row.get("departure_date", "")) == departure_date
        and str(row.get("cabin", "")).lower() == cabin.lower()
        and str(row.get("trip_type", "one-way")) == "one-way"
    )


def web_round_trip_row_matches(
    row: dict[str, Any],
    *,
    origin: str,
    destination: str,
    departure_date: str,
    return_origin: str,
    return_destination: str,
    return_date: str,
    cabin: str,
) -> bool:
    source_name = str(row.get("source_name") or row.get("source") or "").strip().lower()
    if source_name in ONE_WAY_ONLY_ROUND_TRIP_SOURCES:
        return False
    return (
        str(row.get("origin", "")).upper() == origin.upper()
        and str(row.get("destination", "")).upper() == destination.upper()
        and str(row.get("departure_date", "")) == departure_date
        and str(row.get("return_origin", "")).upper() == return_origin.upper()
        and str(row.get("return_destination", "")).upper() == return_destination.upper()
        and str(row.get("return_date", "")) == return_date
        and str(row.get("cabin", "")).lower() == cabin.lower()
        and str(row.get("trip_type", "")) == "round-trip"
    )


def adapt_web_award_row(row: dict[str, Any], *, evidence_source: Path | None = None) -> dict[str, Any]:
    points = numeric(row.get("points"), 0)
    taxes_usd = numeric(row.get("taxes_usd"), 0)
    effective_usd = numeric(row.get("effective_usd"), 0)
    points_value_usd = max(0.0, effective_usd - taxes_usd)
    cpp = (points_value_usd * 100 / points) if points else 0.0
    source_name = str(row.get("source_name") or "web").strip().lower()
    program = f"{source_name.title()} Web"
    flags = ", ".join(
        value
        for value in [
            str(row.get("flags") or "").strip(),
            f"confidence:{row.get('confidence')}" if row.get("confidence") else "",
        ]
        if value
    )
    return {
        **row,
        "source_type": "web_award",
        "source": source_name,
        "program": program,
        "bookable": row.get("bookable") is True,
        "comparable": row.get("bookable") is True and row.get("effective_usd") not in (None, ""),
        "mileage_cost": int(points),
        "taxes_amount": round(taxes_usd, 2),
        "taxes_currency": "USD",
        "taxes_usd": round(taxes_usd, 2),
        "points_value_usd": round(points_value_usd, 2),
        "cents_per_point": round(cpp, 4),
        "flags": flags,
    }


def deduplicate_award_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (
            row.get("source"),
            row.get("origin"),
            row.get("destination"),
            row.get("departure_date"),
            row.get("depart_time"),
            row.get("arrive_time"),
            row.get("flight_numbers"),
            row.get("cabin"),
            row.get("mileage_cost"),
            row.get("taxes_usd"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
