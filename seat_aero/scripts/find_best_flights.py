from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from flight_search_common.formatting import (
    arrival_label,
    cents_to_amount,
    is_next_day,
    money,
    normalize_airport,
    points,
    slug,
    source_from_path,
    time_label,
)
from flight_search_common.io import load_json, markdown_escape, write_csv, write_json
from flight_search_common.preferences import DEFAULT_PREFERENCES_PATH, load_preferences
from flight_search_common.scoring import append_flag, configured_time_penalty

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"


def project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return WORKSPACE_ROOT / path


def fetch_json(url: str, timeout_seconds: float = 60) -> Any:
    request = Request(url, headers={"User-Agent": "FlightSearchPipeline/1.0"})
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.load(response)


def ensure_saved_search(
    *,
    origin: str,
    destination: str,
    search_date: str,
    base_url: str,
    output_dir: Path,
    refresh: bool,
    sources: list[str] | None = None,
    timeout_seconds: float = 60,
) -> tuple[Path, Path]:
    source_filter = ",".join(source.strip().lower() for source in sources or [] if source.strip())
    source_suffix = f"_sources_{slug(source_filter.replace(',', '_'))}" if source_filter else ""
    stem = f"{slug(origin)}_{slug(destination)}_{search_date}{source_suffix}"
    raw_search_path = output_dir / f"{stem}_search_raw.json"
    trip_dir = output_dir / f"{stem}_trip_details"

    output_dir.mkdir(parents=True, exist_ok=True)
    trip_dir.mkdir(parents=True, exist_ok=True)

    if raw_search_path.exists() and not refresh:
        search_payload = load_json(raw_search_path)
    else:
        query_payload = {
            "origin_airport": normalize_airport(origin),
            "destination_airport": normalize_airport(destination),
            "start_date": search_date,
            "end_date": search_date,
            "take": 1000,
            "include_trips": "true",
            "minify_trips": "true",
        }
        if source_filter:
            query_payload["sources"] = source_filter
        query = urlencode(query_payload)
        search_payload = fetch_json(f"{base_url.rstrip('/')}/search?{query}", timeout_seconds)
        write_json(raw_search_path, search_payload)

    for item in search_payload.get("data", []):
        availability_id = item["ID"]
        source = item.get("Source", "unknown")
        detail_path = trip_dir / f"{source}_{availability_id}.json"
        if detail_path.exists() and not refresh:
            continue
        detail_payload = fetch_json(f"{base_url.rstrip('/')}/trips/{availability_id}", timeout_seconds)
        write_json(detail_path, detail_payload)

    return raw_search_path, trip_dir


def read_cached_fx_snapshot(cache_dir: Path, base_currency: str) -> dict[str, Any] | None:
    snapshots = sorted(cache_dir.glob(f"*_{base_currency}.json"))
    if not snapshots:
        return None
    return load_json(snapshots[-1])


def fetch_fx_snapshot(preferences: dict[str, Any]) -> dict[str, Any]:
    currency = preferences.get("currency", {})
    base_currency = currency.get("base", "USD")
    latest_url = currency.get("latest_url", "https://api.frankfurter.dev/v2/rates")
    timeout_seconds = float(currency.get("timeout_seconds", 20))
    query = urlencode({"base": base_currency})
    payload = fetch_json(f"{latest_url}?{query}", timeout_seconds)
    if isinstance(payload, list):
        rates = {item["quote"]: float(item["rate"]) for item in payload if item.get("quote")}
        dates = sorted({item.get("date") for item in payload if item.get("date")})
        return {
            "amount": 1.0,
            "base": base_currency,
            "date": dates[-1] if dates else date.today().isoformat(),
            "rates": rates,
        }
    return payload


def load_fx_rates(preferences: dict[str, Any], *, offline_fx: bool = False) -> tuple[dict[str, float], str]:
    currency = preferences.get("currency", {})
    base_currency = currency.get("base", "USD")
    cache_dir = project_path(currency.get("cache_dir", "data/fx"))
    cache_dir.mkdir(parents=True, exist_ok=True)

    snapshot: dict[str, Any] | None = None
    source = "missing"
    if not offline_fx:
        try:
            snapshot = fetch_fx_snapshot(preferences)
            snapshot_date = snapshot.get("date") or date.today().isoformat()
            write_json(cache_dir / f"{snapshot_date}_{base_currency}.json", snapshot)
            source = f"live:{snapshot_date}"
        except (OSError, URLError, TimeoutError, ValueError):
            snapshot = read_cached_fx_snapshot(cache_dir, base_currency)
            if snapshot:
                source = f"cache:{snapshot.get('date', 'unknown')}"
    else:
        snapshot = read_cached_fx_snapshot(cache_dir, base_currency)
        if snapshot:
            source = f"cache:{snapshot.get('date', 'unknown')}"

    rates = {base_currency: 1.0}
    if snapshot and isinstance(snapshot.get("rates"), dict):
        rates.update({key: float(value) for key, value in snapshot["rates"].items()})
    return rates, source


def convert_to_usd(amount: float, currency: str, rates: dict[str, float]) -> tuple[float | None, bool]:
    currency = currency or "USD"
    if currency == "USD":
        return amount, True
    rate = rates.get(currency)
    if not rate:
        return None, False
    return amount / rate, True


def program_value(source: str, preferences: dict[str, Any]) -> tuple[str, float, bool]:
    points_config = preferences.get("points", {})
    programs = points_config.get("programs", {})
    default_cpp = float(points_config.get("default_cents_per_point", 2.0))
    config = programs.get(source)
    if not config:
        return source, default_cpp, True
    return config.get("label", source), float(config["cents_per_point"]), False


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def build_full_rows(trip_details_dir: Path, preferences: dict[str, Any], fx_rates: dict[str, float], fx_source: str) -> list[dict[str, Any]]:
    traveler = preferences.get("traveler", {})
    ranking = preferences.get("ranking", {})
    time_rules = ranking.get("time_penalties", {})
    passengers = int(traveler.get("passengers", 1))
    required_seats = max(passengers, int(traveler.get("minimum_remaining_seats", 1)))
    max_stops_preference = int(traveler.get("max_stops_preference", 1))
    preferred_cabins = set(traveler.get("preferred_cabins", []))

    stop_penalty = float(ranking.get("stop_penalty_usd", 50))
    duration_penalty_per_hour = float(ranking.get("duration_penalty_usd_per_hour", 5))
    next_day_penalty = float(ranking.get("next_day_arrival_penalty_usd", 75))
    seat_credit = float(ranking.get("seat_credit_usd", 2))
    seat_credit_cap = int(ranking.get("seat_credit_cap", 9))

    rows = []
    for path in sorted(trip_details_dir.glob("*.json")):
        source = source_from_path(path)
        program_label, cpp, used_default_cpp = program_value(source, preferences)
        payload = load_json(path)

        for trip in payload.get("data", []):
            remaining_seats = int(trip.get("RemainingSeats") or 0)
            stops = int(trip.get("Stops") or 0)
            duration_minutes = int(trip.get("TotalDuration") or 0)
            duration_hours = duration_minutes / 60 if duration_minutes else 0
            mileage_cost = int(trip.get("MileageCost") or 0)
            taxes_amount = cents_to_amount(trip.get("TotalTaxes"))
            taxes_currency = trip.get("TaxesCurrency") or "USD"
            taxes_usd, fx_available = convert_to_usd(taxes_amount, taxes_currency, fx_rates)
            points_value_usd = mileage_cost * cpp / 100
            effective_usd = points_value_usd + taxes_usd if taxes_usd is not None else None

            departs_at = trip.get("DepartsAt", "")
            arrives_at = trip.get("ArrivesAt", "")
            depart_penalty, depart_flags = configured_time_penalty(departs_at, time_rules.get("departure", []))
            arrive_penalty, arrive_flags = configured_time_penalty(arrives_at, time_rules.get("arrival", []))
            next_day = is_next_day(departs_at, arrives_at)
            seat_credit_amount = min(max(remaining_seats, 0), seat_credit_cap) * seat_credit

            comparable = effective_usd is not None
            bookable = remaining_seats >= required_seats
            score = None
            if comparable:
                score = (
                    effective_usd
                    + stops * stop_penalty
                    + duration_hours * duration_penalty_per_hour
                    + depart_penalty
                    + arrive_penalty
                    + (next_day_penalty if next_day else 0)
                    - seat_credit_amount
                )

            flags = []
            if used_default_cpp:
                flags.append("default_cpp")
            if not fx_available:
                flags.append(f"missing_fx:{taxes_currency}")
            if not bookable:
                flags.append("not_enough_seats")
            if stops > max_stops_preference:
                flags.append("exceeds_preferred_stops")
            if preferred_cabins and trip.get("Cabin", "") not in preferred_cabins:
                flags.append("not_preferred_cabin")
            if next_day:
                flags.append("next_day_arrival")
            flags.extend(depart_flags)
            flags.extend(arrive_flags)

            rows.append(
                {
                    "source": source,
                    "program": program_label,
                    "used_default_cpp": used_default_cpp,
                    "cents_per_point": cpp,
                    "flight_numbers": trip.get("FlightNumbers", ""),
                    "cabin": trip.get("Cabin", ""),
                    "stops": stops,
                    "connections": ", ".join(trip.get("Connections") or []),
                    "carriers": trip.get("Carriers", ""),
                    "remaining_seats": remaining_seats,
                    "bookable": bookable,
                    "comparable": comparable,
                    "departs_at_raw": departs_at,
                    "arrives_at_raw": arrives_at,
                    "depart_time": time_label(departs_at),
                    "arrive_time": arrival_label(departs_at, arrives_at),
                    "duration_minutes": duration_minutes,
                    "mileage_cost": mileage_cost,
                    "taxes_amount": round(taxes_amount, 2),
                    "taxes_currency": taxes_currency,
                    "taxes_usd": round(taxes_usd, 2) if taxes_usd is not None else "",
                    "fx_source": fx_source,
                    "points_value_usd": round(points_value_usd, 2),
                    "effective_usd": round(effective_usd, 2) if effective_usd is not None else "",
                    "stop_penalty_usd": round(stops * stop_penalty, 2),
                    "duration_penalty_usd": round(duration_hours * duration_penalty_per_hour, 2),
                    "time_penalty_usd": round(depart_penalty + arrive_penalty, 2),
                    "next_day_penalty_usd": round(next_day_penalty if next_day else 0, 2),
                    "seat_credit_usd": round(seat_credit_amount, 2),
                    "score": round(score, 2) if score is not None else "",
                    "expensive_flag": False,
                    "dynamic_price_threshold_usd": "",
                    "flags": ", ".join(flags),
                    "aircraft": ", ".join(trip.get("Aircraft") or []),
                    "fare_classes": ", ".join(trip.get("FareClasses") or []),
                    "availability_id": trip.get("AvailabilityID", ""),
                    "trip_id": trip.get("ID", ""),
                }
            )

    return sorted(
        rows,
        key=lambda row: (
            row["departs_at_raw"],
            row["flight_numbers"],
            row["cabin"],
            row["source"],
            row["mileage_cost"],
        ),
    )


def apply_dynamic_price_flags(rows: list[dict[str, Any]], preferences: dict[str, Any]) -> None:
    dynamic = preferences.get("filtering", {}).get("dynamic_price", {})
    if not dynamic.get("enabled", True):
        return

    percentile_value = float(dynamic.get("percentile", 75))
    best_multiplier = float(dynamic.get("best_multiplier", 2.0))
    best_buffer = float(dynamic.get("best_buffer_usd", 100))

    by_cabin: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["bookable"] and row["comparable"]:
            by_cabin[row["cabin"]].append(float(row["effective_usd"]))

    thresholds = {}
    for cabin, values in by_cabin.items():
        cabin_best = min(values)
        cabin_p = percentile(values, percentile_value)
        if cabin_p is None:
            continue
        thresholds[cabin] = min(cabin_p, cabin_best * best_multiplier + best_buffer)

    for row in rows:
        threshold = thresholds.get(row["cabin"])
        if threshold is None:
            continue
        row["dynamic_price_threshold_usd"] = round(threshold, 2)
        if row["bookable"] and row["comparable"] and float(row["effective_usd"]) > threshold:
            row["expensive_flag"] = True
            row["flags"] = append_flag(row["flags"], "expensive")


def best_deduped_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if row["bookable"] and row["comparable"] and not row["expensive_flag"]
    ]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        key = (
            row["departs_at_raw"],
            row["arrives_at_raw"],
            row["flight_numbers"],
            row["cabin"],
        )
        groups[key].append(row)

    best_rows = []
    for group_rows in groups.values():
        ordered = sorted(group_rows, key=lambda row: (float(row["score"]), float(row["effective_usd"]), row["source"]))
        primary = dict(ordered[0])
        primary["alternates"] = "; ".join(
            f"{row['program']} {points(row['mileage_cost'])} + {money(float(row['taxes_amount']), row['taxes_currency'])}"
            for row in ordered[1:]
        )
        primary["alternate_count"] = len(ordered) - 1
        best_rows.append(primary)

    best_rows.sort(key=lambda row: (float(row["score"]), float(row["effective_usd"]), row["departs_at_raw"]))
    if limit > 0:
        return best_rows[:limit]
    return best_rows


FULL_FIELDNAMES = [
    "source",
    "program",
    "used_default_cpp",
    "cents_per_point",
    "flight_numbers",
    "cabin",
    "stops",
    "connections",
    "carriers",
    "remaining_seats",
    "bookable",
    "comparable",
    "depart_time",
    "arrive_time",
    "duration_minutes",
    "mileage_cost",
    "taxes_amount",
    "taxes_currency",
    "taxes_usd",
    "fx_source",
    "points_value_usd",
    "effective_usd",
    "stop_penalty_usd",
    "duration_penalty_usd",
    "time_penalty_usd",
    "next_day_penalty_usd",
    "seat_credit_usd",
    "score",
    "expensive_flag",
    "dynamic_price_threshold_usd",
    "flags",
    "aircraft",
    "fare_classes",
    "availability_id",
    "trip_id",
    "departs_at_raw",
    "arrives_at_raw",
]


BEST_FIELDNAMES = FULL_FIELDNAMES + ["alternate_count", "alternates"]


def write_markdown(path: Path, rows: list[dict[str, Any]], *, title: str, preferences: dict[str, Any], fx_source: str) -> None:
    ranking = preferences.get("ranking", {})
    dynamic = preferences.get("filtering", {}).get("dynamic_price", {})

    lines = [
        f"# {title}",
        "",
        "## Ranking Rules",
        "",
        f"- FX source: `{fx_source}`",
        f"- Score starts with effective USD, then adds {ranking.get('stop_penalty_usd', 50)} per stop.",
        f"- Duration penalty: {ranking.get('duration_penalty_usd_per_hour', 5)} per travel hour.",
        f"- Next-day arrival penalty: {ranking.get('next_day_arrival_penalty_usd', 75)}.",
        f"- Seat credit: {ranking.get('seat_credit_usd', 2)} per seat, capped at {ranking.get('seat_credit_cap', 9)} seats.",
        f"- Dynamic expensive filter: p{dynamic.get('percentile', 75)} by cabin or best * {dynamic.get('best_multiplier', 2.0)} + {dynamic.get('best_buffer_usd', 100)}, whichever is lower.",
        "",
        "Seats.aero timestamps are treated as displayed wall-clock times; no timezone conversion is applied.",
        "",
        "## Best Flights",
        "",
        "| Rank | Depart | Arrive | Flights | Program | Cabin | Stops | Seats | Miles + Taxes | Effective USD | Score | Flags | Alternates |",
        "|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|---|",
    ]

    for index, row in enumerate(rows, start=1):
        price = f"{points(row['mileage_cost'])} + {money(float(row['taxes_amount']), row['taxes_currency'])}"
        alternates = row.get("alternates") or ""
        lines.append(
            "| "
            + " | ".join(
                markdown_escape(value)
                for value in [
                    index,
                    row["depart_time"],
                    row["arrive_time"],
                    row["flight_numbers"],
                    row["program"],
                    row["cabin"],
                    row["stops"],
                    row["remaining_seats"],
                    price,
                    money(float(row["effective_usd"]), "USD"),
                    row["score"],
                    row["flags"],
                    alternates,
                ]
            )
            + " |"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def output_paths(output_dir: Path, origin: str, destination: str, search_date: str) -> dict[str, Path]:
    stem = f"{slug(origin)}_{slug(destination)}_{search_date}"
    return {
        "full_csv": output_dir / f"{stem}_normalized_full.csv",
        "full_json": output_dir / f"{stem}_normalized_full.json",
        "best_csv": output_dir / f"{stem}_best_flights.csv",
        "best_json": output_dir / f"{stem}_best_flights.json",
        "best_md": output_dir / f"{stem}_best_flights.md",
    }


def run_pipeline(
    *,
    origin: str,
    destination: str,
    search_date: str,
    base_url: str,
    output_dir: Path,
    preferences_path: Path,
    refresh: bool,
    offline_fx: bool,
    best_limit: int | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    preferences = load_preferences(preferences_path)
    raw_search_path, trip_dir = ensure_saved_search(
        origin=origin,
        destination=destination,
        search_date=search_date,
        base_url=base_url,
        output_dir=output_dir,
        refresh=refresh,
        sources=sources,
    )
    fx_rates, fx_source = load_fx_rates(preferences, offline_fx=offline_fx)
    full_rows = build_full_rows(trip_dir, preferences, fx_rates, fx_source)
    if sources:
        allowed_sources = {source.strip().lower() for source in sources if source.strip()}
        full_rows = [row for row in full_rows if str(row.get("source") or "").strip().lower() in allowed_sources]
    apply_dynamic_price_flags(full_rows, preferences)

    configured_limit = int(preferences.get("outputs", {}).get("best_report_limit", 40))
    limit = configured_limit if best_limit is None else best_limit
    best_rows = best_deduped_rows(full_rows, limit)

    paths = output_paths(output_dir, origin, destination, search_date)
    write_json(paths["full_json"], full_rows)
    write_json(paths["best_json"], best_rows)
    write_csv(paths["full_csv"], full_rows, FULL_FIELDNAMES)
    write_csv(paths["best_csv"], best_rows, BEST_FIELDNAMES)
    write_markdown(
        paths["best_md"],
        best_rows,
        title=f"{normalize_airport(origin)} to {normalize_airport(destination)} Best Award Flights on {search_date}",
        preferences=preferences,
        fx_source=fx_source,
    )

    return {
        "raw_search": str(raw_search_path),
        "trip_details": str(trip_dir),
        "fx_source": fx_source,
        "full_count": len(full_rows),
        "best_count": len(best_rows),
        "sources": sources or [],
        "outputs": {key: str(value) for key, value in paths.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Find and rank best award flights from Seats.aero data.")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--preferences", default=str(DEFAULT_PREFERENCES_PATH))
    parser.add_argument("--refresh", action="store_true", help="Force refetching search and trip-detail data from the local API.")
    parser.add_argument("--offline-fx", action="store_true", help="Use cached FX only; do not call the FX provider.")
    parser.add_argument("--best-limit", type=int, default=None)
    parser.add_argument("--sources", default="", help="Comma-delimited Seats.aero sources to include, e.g. united,aeroplan.")
    args = parser.parse_args()

    summary = run_pipeline(
        origin=args.origin,
        destination=args.destination,
        search_date=args.date,
        base_url=args.base_url,
        output_dir=Path(args.output_dir),
        preferences_path=Path(args.preferences),
        refresh=args.refresh,
        offline_fx=args.offline_fx,
        best_limit=args.best_limit,
        sources=[value.strip().lower() for value in args.sources.split(",") if value.strip()] or None,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
