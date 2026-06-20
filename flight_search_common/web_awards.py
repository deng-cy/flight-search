from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .formatting import slug
from .io import load_json
from .provider_catalog import load_provider_catalog


def provider_catalog(workspace_root: Path):
    catalog_path = workspace_root / "config" / "provider_catalog.yaml"
    return load_provider_catalog(catalog_path if catalog_path.exists() else None)


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
    source_names: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    candidate_paths = list(paths) if paths is not None else award_web_candidate_paths(
        workspace_root,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        cabin=cabin,
    )
    allowed_sources = {str(source).strip().lower() for source in source_names or [] if str(source).strip()}
    rows: list[dict[str, Any]] = []
    for path in candidate_paths:
        payload = load_json(path)
        if not isinstance(payload, list):
            continue
        rows.extend(
            adapt_web_award_row(row, workspace_root=workspace_root, evidence_source=path)
            for row in payload
            if isinstance(row, dict)
            and source_allowed(row, allowed_sources)
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
    source_names: Iterable[str] | None = None,
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
    allowed_sources = {str(source).strip().lower() for source in source_names or [] if str(source).strip()}
    rows: list[dict[str, Any]] = []
    for path in candidate_paths:
        payload = load_json(path)
        if not isinstance(payload, list):
            continue
        rows.extend(
            adapt_web_award_row(row, workspace_root=workspace_root, evidence_source=path)
            for row in payload
            if isinstance(row, dict)
            and source_allowed(row, allowed_sources)
            and web_round_trip_row_matches(
                row,
                workspace_root=workspace_root,
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


def source_allowed(row: dict[str, Any], allowed_sources: set[str]) -> bool:
    if not allowed_sources:
        return True
    source_name = str(row.get("source_name") or row.get("source") or "").strip().lower()
    return source_name in allowed_sources


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
    workspace_root: Path,
    origin: str,
    destination: str,
    departure_date: str,
    return_origin: str,
    return_destination: str,
    return_date: str,
    cabin: str,
) -> bool:
    source_name = str(row.get("source_name") or row.get("source") or "").strip().lower()
    if source_name in provider_catalog(workspace_root).one_way_only_round_trip_sources():
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


def adapt_web_award_row(
    row: dict[str, Any],
    *,
    workspace_root: Path | None = None,
    evidence_source: Path | None = None,
) -> dict[str, Any]:
    points = numeric(row.get("points"), 0)
    taxes_usd = numeric(row.get("taxes_usd"), 0)
    effective_usd = numeric(row.get("effective_usd"), 0)
    points_value_usd = max(0.0, effective_usd - taxes_usd)
    cpp = (points_value_usd * 100 / points) if points else 0.0
    source_name = str(row.get("source_name") or "web").strip().lower()
    catalog = provider_catalog(workspace_root) if workspace_root is not None else load_provider_catalog()
    program = catalog.award_web_label(source_name)
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


def row_detail_score(row: dict[str, Any]) -> int:
    legs = row.get("legs") if isinstance(row.get("legs"), dict) else {}
    outbound = legs.get("outbound") if isinstance(legs.get("outbound"), dict) else {}
    return_leg = legs.get("return") if isinstance(legs.get("return"), dict) else {}
    fields = [
        row.get("depart_time"),
        row.get("arrive_time"),
        row.get("flight_numbers"),
        row.get("duration_minutes"),
        row.get("outbound_depart_time"),
        row.get("outbound_arrive_time"),
        row.get("outbound_flight_numbers"),
        row.get("return_depart_time"),
        row.get("return_arrive_time"),
        row.get("return_flight_numbers"),
        outbound.get("depart_time"),
        outbound.get("arrive_time"),
        outbound.get("flight_numbers"),
        return_leg.get("depart_time"),
        return_leg.get("arrive_time"),
        return_leg.get("flight_numbers"),
    ]
    return sum(1 for value in fields if value not in (None, ""))


def deduplicate_award_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: dict[tuple[Any, ...], int] = {}
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
        existing_index = seen.get(key)
        if existing_index is not None:
            if row_detail_score(row) > row_detail_score(deduped[existing_index]):
                deduped[existing_index] = row
            continue
        seen[key] = len(deduped)
        deduped.append(row)
    return deduped
