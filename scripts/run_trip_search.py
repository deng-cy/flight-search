from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, TypeVar


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CASH_ROOT = WORKSPACE_ROOT / "cash"
SEAT_AERO_SCRIPTS = WORKSPACE_ROOT / "seat_aero" / "scripts"
for path in (WORKSPACE_ROOT, CASH_ROOT, SEAT_AERO_SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cash_search.pipeline import DEFAULT_PREFERENCES_PATH, load_preferences, run_pipeline as run_cash_pipeline
from find_best_flights import run_pipeline as run_award_pipeline
from flight_search_common.formatting import money, normalize_airport, points, slug
from flight_search_common.io import load_json, write_json


DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "reports"
CASH_PRICE_TOLERANCE_USD = 0.01
AWARD_PROGRAM_CODES = {
    "aeroplan": "AC",
    "alaska": "AS",
    "american": "AA",
    "azul": "AD",
    "delta": "DL",
    "flyingblue": "AF",
    "united": "UA",
    "velocity": "VA",
    "virginatlantic": "VS",
}
T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True)
class LegContext:
    direction: str
    origin: str
    destination: str
    date: str

    @property
    def key(self) -> str:
        return f"{self.direction}_{slug(self.origin)}_{slug(self.destination)}_{self.date}"

    @property
    def route(self) -> str:
        return f"{self.origin} -> {self.destination}"

    @property
    def label(self) -> str:
        return f"{self.route} on {self.date}"


@dataclass(frozen=True)
class CashItineraryContext:
    outbound: LegContext
    return_leg: LegContext
    trip_type: str

    @property
    def key(self) -> str:
        return "_".join(
            [
                "cash",
                slug(self.outbound.origin),
                slug(self.outbound.destination),
                self.outbound.date,
                slug(self.return_leg.origin),
                slug(self.return_leg.destination),
                self.return_leg.date,
                self.trip_type.replace("-", "_"),
            ]
        )

    @property
    def route(self) -> str:
        return f"{self.outbound.route} / {self.return_leg.route}"

    @property
    def dates(self) -> str:
        return f"{self.outbound.date} / {self.return_leg.date}"


@dataclass(frozen=True)
class TripSearchPlan:
    outbound_legs: list[LegContext]
    return_legs: list[LegContext]
    cash_one_way_legs: list[LegContext]
    cash_itineraries: list[CashItineraryContext]


def csv_values(value: str, *, uppercase: bool = False) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if uppercase:
        return [item.upper() for item in values]
    return values


def choose_cash_trip_type(outbound: LegContext, return_leg: LegContext) -> str:
    if outbound.origin == return_leg.destination and outbound.destination == return_leg.origin:
        return "round-trip"
    return "multi-city"


def expand_trip_search(
    *,
    origins: list[str],
    destinations: list[str],
    outbound_dates: list[str],
    return_dates: list[str],
) -> TripSearchPlan:
    normalized_origins = [normalize_airport(value) for value in origins]
    normalized_destinations = [normalize_airport(value) for value in destinations]

    outbound_legs = [
        LegContext("outbound", origin, destination, departure_date)
        for origin in normalized_origins
        for destination in normalized_destinations
        for departure_date in outbound_dates
    ]
    return_legs = [
        LegContext("return", destination, origin, return_date)
        for destination in normalized_destinations
        for origin in normalized_origins
        for return_date in return_dates
    ]
    cash_itineraries = [
        CashItineraryContext(outbound, return_leg, choose_cash_trip_type(outbound, return_leg))
        for outbound in outbound_legs
        for return_leg in return_legs
    ]
    return TripSearchPlan(outbound_legs, return_legs, [*outbound_legs, *return_legs], cash_itineraries)


def run_ordered_workers(
    items: list[T],
    *,
    workers: int,
    runner: Callable[[T], U],
) -> list[U]:
    if not items:
        return []
    max_workers = max(1, min(workers, len(items)))
    if max_workers == 1:
        return [runner(item) for item in items]

    results: list[U | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(runner, item): index
            for index, item in enumerate(items)
        }
        for future in as_completed(future_to_index):
            results[future_to_index[future]] = future.result()

    return [result for result in results if result is not None]


def search_stem(origins: list[str], destinations: list[str], outbound_dates: list[str], return_dates: list[str], cabin: str) -> str:
    return "_".join(
        [
            "_".join(slug(value) for value in origins),
            "to",
            "_".join(slug(value) for value in destinations),
            "out",
            "_".join(outbound_dates),
            "return",
            "_".join(return_dates),
            cabin.replace("-", "_"),
        ]
    )


def numeric(value: Any, default: float = 10**12) -> float:
    if value in (None, ""):
        return default
    return float(value)


def component_value(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def compact_money(amount: Any, currency: str = "USD") -> str:
    if amount in (None, ""):
        return ""
    value = float(amount)
    if currency == "USD":
        return f"${value:,.2f}"
    return f"{currency} {value:,.2f}"


def award_program_code(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "").strip().lower()
    if source in AWARD_PROGRAM_CODES:
        return AWARD_PROGRAM_CODES[source]
    program = str(row.get("program") or source).upper()
    return program


def award_price(row: dict[str, Any]) -> str:
    prefix = award_program_code(row)
    return f"{prefix} {points(row.get('mileage_cost'))} + {compact_money(row.get('taxes_amount'), row.get('taxes_currency') or 'USD')}"


def cpp_label(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):.2f} cpp"


def award_cpp_label(row: dict[str, Any]) -> str:
    return cpp_label(row.get("cents_per_point"))


def award_program_key(row: dict[str, Any]) -> str:
    key = str(row.get("source") or row.get("program") or award_program_code(row)).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", key).strip("_") or "award"


def award_component(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": award_program_key(row),
        "label": str(row.get("program") or award_program_code(row)),
        "points": numeric(row.get("mileage_cost"), 0),
        "cpp": numeric(row.get("cents_per_point"), 0),
    }


def award_cash_component_usd(row: dict[str, Any]) -> float:
    if row.get("taxes_usd") not in (None, ""):
        return numeric(row.get("taxes_usd"), 0)
    effective = numeric(row.get("effective_usd"), 0)
    if row.get("points_value_usd") not in (None, ""):
        return max(0.0, effective - numeric(row.get("points_value_usd"), 0))
    component = award_component(row)
    return max(0.0, effective - component["points"] * component["cpp"] / 100)


def combined_cpp_label(*rows: dict[str, Any]) -> str:
    labels = [str(row.get("cpp") or "") for row in rows if row.get("cpp")]
    return " / ".join(dict.fromkeys(labels))


def combined_cpp_num(*rows: dict[str, Any]) -> float:
    weighted_total = 0.0
    points_total = 0.0
    fallback_values = []
    for row in rows:
        cpp = numeric(row.get("cpp_num"), 0)
        award_points = numeric(row.get("award_points"), 0)
        if cpp and award_points:
            weighted_total += cpp * award_points
            points_total += award_points
        elif cpp:
            fallback_values.append(cpp)
    if points_total:
        return weighted_total / points_total
    if fallback_values:
        return sum(fallback_values) / len(fallback_values)
    return 0.0


def combined_award_components(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    components = []
    for row in rows:
        components.extend(row.get("award_components") or [])
    return components


def combined_cash_component(*rows: dict[str, Any]) -> float:
    return sum(component_value(row.get("cash_component_usd")) for row in rows)


def hour_from_time(value: Any) -> int | None:
    match = re.search(r"\b(\d{1,2}):\d{2}\b", str(value or ""))
    if not match:
        return None
    hour = int(match.group(1))
    return hour if 0 <= hour <= 23 else None


def time_hour_counts(row: dict[str, Any]) -> list[int]:
    counts = [0 for _ in range(24)]
    for key in ("outbound_depart", "outbound_arrive", "return_depart", "return_arrive"):
        hour = hour_from_time(row.get(key))
        if hour is not None:
            counts[hour] += 1
    return counts


def hours_in_window(start: str, end: str) -> list[int]:
    start_hour = int(start.split(":", 1)[0])
    end_hour = int(end.split(":", 1)[0])
    if start_hour <= end_hour:
        return list(range(start_hour, end_hour + 1))
    return list(range(start_hour, 24)) + list(range(0, end_hour + 1))


def hourly_time_defaults(preferences: dict[str, Any]) -> list[float]:
    defaults = [0.0 for _ in range(24)]
    for windows in (preferences.get("ranking", {}).get("time_penalties") or {}).values():
        for window in windows or []:
            penalty = component_value(window.get("penalty_usd"))
            for hour in hours_in_window(str(window.get("start", "00:00")), str(window.get("end", "00:00"))):
                defaults[hour] = max(defaults[hour], penalty)
    return defaults


def point_value_defaults(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    programs: dict[str, dict[str, Any]] = {}
    for row in rows:
        for component in row.get("award_components") or []:
            key = str(component.get("key") or "")
            if not key:
                continue
            programs.setdefault(
                key,
                {
                    "key": key,
                    "label": str(component.get("label") or key),
                    "cpp": numeric(component.get("cpp"), 0),
                },
            )
    return sorted(programs.values(), key=lambda item: item["label"].lower())


def point_value_controls(rows: list[dict[str, Any]]) -> str:
    controls = []
    for program in point_value_defaults(rows):
        key = escape(str(program["key"]), quote=True)
        label = escape(str(program["label"]))
        value = numeric(program.get("cpp"), 0)
        controls.append(
            '<label>'
            f'<span>{label} CPP</span>'
            f'<input data-cpp-control data-program="{key}" type="number" min="0" max="5" step="0.05" value="{value:.2f}">'
            '</label>'
        )
    if not controls:
        return ""
    return '<section class="score-lab point-lab"><h2>Point Values</h2><div class="cpp-grid">' + "".join(controls) + "</div></section>"


def hour_options() -> str:
    return "".join(f'<option value="{hour}">{hour:02d}:00</option>' for hour in range(24))


def short_notes(flags: Any, *, trip_type: str | None = None, open_jaw: bool = False) -> str:
    values = []
    for item in str(flags or "").split(","):
        label = item.strip().replace("_", " ")
        if not label:
            continue
        if ":" in label:
            key, value = label.split(":", 1)
            label = f"{key}: {value.strip()}"
        values.append(label)
    if trip_type == "multi-city":
        values.insert(0, "open jaw cash fare")
    elif trip_type == "round-trip":
        values.insert(0, "round trip cash fare")
    if open_jaw:
        values.insert(0, "airport pair differs")
    return ", ".join(dict.fromkeys(values))


def better_note(base: str, addition: str) -> str:
    if not base:
        return addition
    if addition in base:
        return base
    return f"{base}, {addition}"


def signed_money_delta(value: float) -> str:
    return f"${abs(value):,.2f}"


def compact_error(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if text.startswith("No flights found"):
        return "provider returned no parseable fare"
    if "<!doctype html" in text.lower() or "<html" in text.lower():
        text = text.split("<", 1)[0].strip() or "provider returned an HTML page instead of parsed fares"
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def run_award_leg(
    leg: LegContext,
    *,
    base_url: str,
    output_dir: Path,
    preferences_path: Path,
    refresh: bool,
    offline_fx: bool,
    best_limit: int | None,
) -> dict[str, Any]:
    try:
        summary = run_award_pipeline(
            origin=leg.origin,
            destination=leg.destination,
            search_date=leg.date,
            base_url=base_url,
            output_dir=output_dir,
            preferences_path=preferences_path,
            refresh=refresh,
            offline_fx=offline_fx,
            best_limit=best_limit,
        )
        return {"leg": asdict(leg), "summary": summary, "error": ""}
    except Exception as exc:  # Keep master reports useful when one route/provider fails.
        return {"leg": asdict(leg), "summary": {}, "error": compact_error(exc)}


def run_cash_itinerary(
    itinerary: CashItineraryContext,
    *,
    cabin: str,
    adults: int,
    currency: str,
    fetch_mode: str,
    max_stops: int | None,
    output_dir: Path,
    preferences_path: Path,
    refresh: bool,
) -> dict[str, Any]:
    try:
        summary = run_cash_pipeline(
            origin=itinerary.outbound.origin,
            destination=itinerary.outbound.destination,
            departure_date=itinerary.outbound.date,
            cabin=cabin,
            adults=adults,
            currency=currency,
            fetch_mode=fetch_mode,
            max_stops=max_stops,
            trip_type=itinerary.trip_type,
            return_date=itinerary.return_leg.date,
            return_origin=itinerary.return_leg.origin,
            return_destination=itinerary.return_leg.destination,
            output_dir=output_dir,
            preferences_path=preferences_path,
            refresh=refresh,
        )
        return {"itinerary": itinerary_payload(itinerary), "summary": summary, "error": ""}
    except Exception as exc:
        return {"itinerary": itinerary_payload(itinerary), "summary": {}, "error": compact_error(exc)}


def run_cash_one_way_leg(
    leg: LegContext,
    *,
    cabin: str,
    adults: int,
    currency: str,
    fetch_mode: str,
    max_stops: int | None,
    output_dir: Path,
    preferences_path: Path,
    refresh: bool,
) -> dict[str, Any]:
    try:
        summary = run_cash_pipeline(
            origin=leg.origin,
            destination=leg.destination,
            departure_date=leg.date,
            cabin=cabin,
            adults=adults,
            currency=currency,
            fetch_mode=fetch_mode,
            max_stops=max_stops,
            trip_type="one-way",
            output_dir=output_dir,
            preferences_path=preferences_path,
            refresh=refresh,
        )
        return {"cash_leg": asdict(leg), "summary": summary, "error": ""}
    except Exception as exc:
        return {"cash_leg": asdict(leg), "summary": {}, "error": compact_error(exc)}


def itinerary_payload(itinerary: CashItineraryContext) -> dict[str, Any]:
    return {
        "key": itinerary.key,
        "trip_type": itinerary.trip_type,
        "route": itinerary.route,
        "dates": itinerary.dates,
        "outbound": asdict(itinerary.outbound),
        "return_leg": asdict(itinerary.return_leg),
    }


def load_rows(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    payload = load_json(file_path)
    return payload if isinstance(payload, list) else []


def blank_leg(direction: str, origin: str, destination: str, date: str) -> dict[str, Any]:
    return {
        "direction": direction,
        "origin": origin,
        "destination": destination,
        "date": date,
        "depart_time": "",
        "arrive_time": "",
        "flight_numbers": "",
        "carriers": "",
        "stops": "",
        "duration_minutes": "",
        "duration_display": "",
    }


def cash_leg_from_row(row: dict[str, Any], direction: str, context: dict[str, Any]) -> dict[str, Any]:
    legs = row.get("legs") if isinstance(row.get("legs"), dict) else {}
    leg = legs.get(direction) if isinstance(legs.get(direction), dict) else {}
    if leg:
        return {**blank_leg(direction, context["origin"], context["destination"], context["date"]), **leg}

    prefix = "outbound" if direction == "outbound" else "return"
    fallback = blank_leg(direction, context["origin"], context["destination"], context["date"])
    if direction == "outbound":
        fallback.update(
            {
                "depart_time": row.get("depart_time", ""),
                "arrive_time": row.get("arrive_time", ""),
                "flight_numbers": row.get("flight_numbers", ""),
                "carriers": row.get("carriers", ""),
                "stops": row.get("stops", ""),
                "duration_minutes": row.get("duration_minutes", ""),
                "duration_display": row.get("duration_display", ""),
            }
        )
    fallback.update(
        {
            "origin": row.get(f"{prefix}_origin") or fallback["origin"],
            "destination": row.get(f"{prefix}_destination") or fallback["destination"],
            "date": row.get(f"{prefix}_date") or fallback["date"],
            "depart_time": row.get(f"{prefix}_depart_time") or fallback["depart_time"],
            "arrive_time": row.get(f"{prefix}_arrive_time") or fallback["arrive_time"],
            "flight_numbers": row.get(f"{prefix}_flight_numbers") or fallback["flight_numbers"],
            "carriers": row.get(f"{prefix}_carriers") or fallback["carriers"],
            "stops": row.get(f"{prefix}_stops") if row.get(f"{prefix}_stops") not in (None, "") else fallback["stops"],
            "duration_minutes": row.get(f"{prefix}_duration_minutes") or fallback["duration_minutes"],
            "duration_display": row.get(f"{prefix}_duration_display") or fallback["duration_display"],
        }
    )
    return fallback


def leg_has_detail(leg: dict[str, Any]) -> bool:
    return any(
        leg.get(field) not in ("", None)
        for field in ("depart_time", "arrive_time", "flight_numbers", "carriers", "duration_display", "duration_minutes")
    ) or leg.get("stops") not in ("", None)


def leg_stop_count(leg: dict[str, Any]) -> float:
    return numeric(leg.get("stops"), 0)


def leg_duration_minutes(leg: dict[str, Any]) -> float:
    return numeric(leg.get("duration_minutes"), 0)


def leg_detail_text(leg: dict[str, Any], *, missing_label: str = "timing unavailable") -> str:
    route_date = f"{leg.get('origin', '')} -> {leg.get('destination', '')} {leg.get('date', '')}".strip()
    if not leg_has_detail(leg):
        return f"{route_date}: {missing_label}"

    timing = " -> ".join(
        value for value in [str(leg.get("depart_time") or ""), str(leg.get("arrive_time") or "")] if value
    )
    parts = [
        timing,
        str(leg.get("flight_numbers") or leg.get("carriers") or ""),
    ]
    if leg.get("stops") not in ("", None):
        parts.append(f"{leg.get('stops')} stop(s)")
    if leg.get("duration_display"):
        parts.append(str(leg["duration_display"]))
    return f"{route_date}: {', '.join(part for part in parts if part)}"


def leg_cell_text(leg: dict[str, Any], *, missing_label: str = "Timing unavailable") -> str:
    if not leg_has_detail(leg):
        return f"{leg.get('origin', '')} -> {leg.get('destination', '')}\n{leg.get('date', '')}\n{missing_label}"
    timing = " -> ".join(
        value for value in [str(leg.get("depart_time") or ""), str(leg.get("arrive_time") or "")] if value
    )
    meta = ", ".join(
        str(value)
        for value in [
            leg.get("flight_numbers") or leg.get("carriers"),
            f"{leg.get('stops')} stop(s)" if leg.get("stops") not in ("", None) else "",
            leg.get("duration_display"),
        ]
        if value not in ("", None)
    )
    return "\n".join(
        part
        for part in [
            f"{leg.get('origin', '')} -> {leg.get('destination', '')}",
            str(leg.get("date") or ""),
            timing,
            meta,
        ]
        if part
    )


def combined_duration(
    outbound: dict[str, Any],
    return_leg: dict[str, Any],
    fallback_label: Any,
    fallback_minutes: Any,
) -> tuple[str, float]:
    outbound_minutes = leg_duration_minutes(outbound)
    return_minutes = leg_duration_minutes(return_leg)
    if outbound_minutes and return_minutes:
        total = outbound_minutes + return_minutes
        return duration_label(total), total
    return str(fallback_label or ""), outbound_minutes or numeric(fallback_minutes, 0)


def top_cash_plan_rows(cash_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for run in cash_runs:
        itinerary = run["itinerary"]
        output = run.get("summary", {}).get("outputs", {}).get("normalized_json")
        candidates = [
            row
            for row in load_rows(output)
            if row.get("bookable") is True and row.get("cash_price_usd") not in ("", None)
        ]
        if not candidates:
            continue
        best = sorted(
            candidates,
            key=lambda row: (
                numeric(row.get("score")),
                numeric(row.get("cash_price_usd")),
                numeric(row.get("duration_minutes")),
            ),
        )[0]
        outbound = itinerary["outbound"]
        return_leg = itinerary["return_leg"]
        outbound_detail = cash_leg_from_row(
            best,
            "outbound",
            {"origin": outbound["origin"], "destination": outbound["destination"], "date": outbound["date"]},
        )
        return_detail = cash_leg_from_row(
            best,
            "return",
            {"origin": return_leg["origin"], "destination": return_leg["destination"], "date": return_leg["date"]},
        )
        cash_detail_status = str(best.get("cash_detail_status") or "")
        if not cash_detail_status:
            if leg_has_detail(outbound_detail) and leg_has_detail(return_detail):
                cash_detail_status = "complete"
            elif leg_has_detail(outbound_detail):
                cash_detail_status = "outbound_only"
            else:
                cash_detail_status = "price_only"
        cash_detail_source = str(best.get("cash_detail_source") or ("provider_parser" if cash_detail_status != "price_only" else "none"))
        notes = short_notes(best.get("flags"), trip_type=itinerary["trip_type"])
        if cash_detail_status == "complete":
            notes = better_note(notes, "return details captured")
        else:
            notes = better_note(notes, "return timing unavailable")
        notes = better_note(notes, "cash price is actual two-leg fare")
        duration_display, duration_minutes = combined_duration(
            outbound_detail,
            return_detail,
            best.get("duration_display", ""),
            best.get("duration_minutes", ""),
        )
        if leg_has_detail(return_detail):
            stops_display = f"{outbound_detail.get('stops', '')} + {return_detail.get('stops', '')}"
            stops_num = leg_stop_count(outbound_detail) + leg_stop_count(return_detail)
        else:
            stops_display = f"{outbound_detail.get('stops', best.get('stops', ''))} + ?"
            stops_num = numeric(best.get("stops"), 0)
        rows.append(
            {
                "kind": "cash",
                "route": itinerary["route"],
                "dates": itinerary["dates"],
                "origin": outbound["origin"],
                "destination": outbound["destination"],
                "outbound_date": outbound["date"],
                "return_origin": return_leg["origin"],
                "return_destination": return_leg["destination"],
                "return_date": return_leg["date"],
                "same_airports": itinerary["trip_type"] == "round-trip",
                "trip_type": itinerary["trip_type"],
                "cash_detail_status": cash_detail_status,
                "cash_detail_source": cash_detail_source,
                "price": compact_money(best.get("cash_price_usd"), "USD"),
                "effective": compact_money(best.get("effective_usd"), "USD"),
                "effective_num": numeric(best.get("effective_usd")),
                "cpp": "",
                "cpp_num": 0.0,
                "award_points": 0.0,
                "award_components": [],
                "cash_component_usd": numeric(best.get("effective_usd"), 0),
                "score": numeric(best.get("score")),
                "score_label": "" if best.get("score") in ("", None) else f"{float(best['score']):.2f}",
                "stop_penalty_base": component_value(best.get("stop_penalty_usd")),
                "duration_penalty_base": component_value(best.get("duration_penalty_usd")),
                "time_penalty_base": component_value(best.get("time_penalty_usd")),
                "next_day_penalty_base": component_value(best.get("next_day_penalty_usd")),
                "seat_credit_base": 0.0,
                "stops": stops_display,
                "stops_num": stops_num,
                "duration": duration_display,
                "duration_minutes": duration_minutes,
                "depart": " / ".join(
                    value for value in [str(outbound_detail.get("depart_time") or ""), str(return_detail.get("depart_time") or "")] if value
                ),
                "arrive": " / ".join(
                    value for value in [str(outbound_detail.get("arrive_time") or ""), str(return_detail.get("arrive_time") or "")] if value
                ),
                "outbound_depart": outbound_detail.get("depart_time", ""),
                "outbound_arrive": outbound_detail.get("arrive_time", ""),
                "return_depart": return_detail.get("depart_time", ""),
                "return_arrive": return_detail.get("arrive_time", ""),
                "provider": "cash",
                "notes": notes,
                "outbound_detail": leg_detail_text(outbound_detail),
                "return_detail": leg_detail_text(return_detail),
                "outbound_cell": leg_cell_text(outbound_detail),
                "return_cell": leg_cell_text(return_detail),
                "outbound_leg_detail": outbound_detail,
                "return_leg_detail": return_detail,
                "evidence": best.get("evidence_path", ""),
                "source_status": "ok",
            }
        )
    return sorted(rows, key=lambda row: (row["score"], row["effective_num"], row["duration_minutes"]))


def cash_one_way_leg_rows(cash_leg_runs: list[dict[str, Any]], *, per_leg_limit: int) -> list[dict[str, Any]]:
    rows = []
    for run in cash_leg_runs:
        leg = run["cash_leg"]
        output = run.get("summary", {}).get("outputs", {}).get("normalized_json")
        candidates = [
            row
            for row in load_rows(output)
            if row.get("bookable") is True and row.get("cash_price_usd") not in ("", None)
        ][:per_leg_limit]
        for row in candidates:
            detail = cash_leg_from_row(
                row,
                "outbound",
                {"origin": leg["origin"], "destination": leg["destination"], "date": leg["date"]},
            )
            status = str(row.get("cash_detail_status") or ("complete" if leg_has_detail(detail) else "price_only"))
            notes = short_notes(row.get("flags"))
            notes = better_note(notes, "cash one-way fare")
            rows.append(
                {
                    "kind": f"{leg['direction']} cash",
                    "direction": leg["direction"],
                    "route": f"{leg['origin']} -> {leg['destination']}",
                    "dates": leg["date"],
                    "origin": leg["origin"],
                    "destination": leg["destination"],
                    "outbound_date": leg["date"] if leg["direction"] == "outbound" else "",
                    "return_origin": leg["origin"] if leg["direction"] == "return" else "",
                    "return_destination": leg["destination"] if leg["direction"] == "return" else "",
                    "return_date": leg["date"] if leg["direction"] == "return" else "",
                    "same_airports": True,
                    "trip_type": "cash one-way",
                    "cash_detail_status": status,
                    "cash_detail_source": str(row.get("cash_detail_source") or "provider_parser"),
                    "price": compact_money(row.get("cash_price_usd"), "USD"),
                    "effective": compact_money(row.get("effective_usd"), "USD"),
                    "effective_num": numeric(row.get("effective_usd")),
                    "cpp": "",
                    "cpp_num": 0.0,
                    "award_points": 0.0,
                    "award_components": [],
                    "cash_component_usd": numeric(row.get("effective_usd"), 0),
                    "score": numeric(row.get("score")),
                    "score_label": "" if row.get("score") in ("", None) else f"{float(row['score']):.2f}",
                    "stop_penalty_base": component_value(row.get("stop_penalty_usd")),
                    "duration_penalty_base": component_value(row.get("duration_penalty_usd")),
                    "time_penalty_base": component_value(row.get("time_penalty_usd")),
                    "next_day_penalty_base": component_value(row.get("next_day_penalty_usd")),
                    "seat_credit_base": 0.0,
                    "stops": detail.get("stops", row.get("stops", "")),
                    "stops_num": leg_stop_count(detail),
                    "duration": detail.get("duration_display") or duration_label(detail.get("duration_minutes")),
                    "duration_minutes": leg_duration_minutes(detail),
                    "depart": detail.get("depart_time", ""),
                    "arrive": detail.get("arrive_time", ""),
                    "outbound_depart": detail.get("depart_time", "") if leg["direction"] == "outbound" else "",
                    "outbound_arrive": detail.get("arrive_time", "") if leg["direction"] == "outbound" else "",
                    "return_depart": detail.get("depart_time", "") if leg["direction"] == "return" else "",
                    "return_arrive": detail.get("arrive_time", "") if leg["direction"] == "return" else "",
                    "provider": "cash",
                    "flight": detail.get("flight_numbers", ""),
                    "notes": notes,
                    "outbound_detail": leg_detail_text(detail) if leg["direction"] == "outbound" else "",
                    "return_detail": leg_detail_text(detail) if leg["direction"] == "return" else "",
                    "outbound_cell": leg_cell_text(detail) if leg["direction"] == "outbound" else "",
                    "return_cell": leg_cell_text(detail) if leg["direction"] == "return" else "",
                    "leg_detail": detail,
                    "source_status": "ok",
                    "raw": row,
                    "leg": leg,
                }
            )
    return sorted(rows, key=lambda row: (row["score"], row["effective_num"], row["duration_minutes"]))


def award_leg_rows(award_runs: list[dict[str, Any]], *, cabin: str, per_leg_limit: int) -> list[dict[str, Any]]:
    rows = []
    for run in award_runs:
        leg = run["leg"]
        best_json = run.get("summary", {}).get("outputs", {}).get("best_json")
        candidates = [
            row
            for row in load_rows(best_json)
            if row.get("bookable") is True
            and row.get("comparable") is True
            and str(row.get("cabin", "")).lower() == cabin.lower()
            and row.get("effective_usd") not in ("", None)
        ][:per_leg_limit]
        for row in candidates:
            rows.append(
                {
                    "kind": f"{leg['direction']} award",
                    "direction": leg["direction"],
                    "route": f"{leg['origin']} -> {leg['destination']}",
                    "dates": leg["date"],
                    "origin": leg["origin"],
                    "destination": leg["destination"],
                    "outbound_date": leg["date"] if leg["direction"] == "outbound" else "",
                    "return_origin": leg["origin"] if leg["direction"] == "return" else "",
                    "return_destination": leg["destination"] if leg["direction"] == "return" else "",
                    "return_date": leg["date"] if leg["direction"] == "return" else "",
                    "same_airports": True,
                    "trip_type": "award one-way",
                    "price": award_price(row),
                    "effective": compact_money(row.get("effective_usd"), "USD"),
                    "effective_num": numeric(row.get("effective_usd")),
                    "cpp": award_cpp_label(row),
                    "cpp_num": numeric(row.get("cents_per_point"), 0),
                    "award_points": numeric(row.get("mileage_cost"), 0),
                    "award_components": [award_component(row)],
                    "cash_component_usd": award_cash_component_usd(row),
                    "score": numeric(row.get("score")),
                    "score_label": "" if row.get("score") in ("", None) else f"{float(row['score']):.2f}",
                    "stop_penalty_base": component_value(row.get("stop_penalty_usd")),
                    "duration_penalty_base": component_value(row.get("duration_penalty_usd")),
                    "time_penalty_base": component_value(row.get("time_penalty_usd")),
                    "next_day_penalty_base": component_value(row.get("next_day_penalty_usd")),
                    "seat_credit_base": component_value(row.get("seat_credit_usd")),
                    "stops": row.get("stops", ""),
                    "stops_num": numeric(row.get("stops"), 0),
                    "duration": duration_label(row.get("duration_minutes")),
                    "duration_minutes": numeric(row.get("duration_minutes"), 0),
                    "depart": row.get("depart_time", ""),
                    "arrive": row.get("arrive_time", ""),
                    "outbound_depart": row.get("depart_time", "") if leg["direction"] == "outbound" else "",
                    "outbound_arrive": row.get("arrive_time", "") if leg["direction"] == "outbound" else "",
                    "return_depart": row.get("depart_time", "") if leg["direction"] == "return" else "",
                    "return_arrive": row.get("arrive_time", "") if leg["direction"] == "return" else "",
                    "provider": row.get("program", row.get("source", "")),
                    "flight": row.get("flight_numbers", ""),
                    "notes": short_notes(row.get("flags")),
                    "outbound_detail": (
                        f"{leg['origin']} -> {leg['destination']} {leg['date']}: "
                        f"{row.get('depart_time', '')} -> {row.get('arrive_time', '')}, "
                        f"{row.get('flight_numbers', '') or row.get('carriers', '')}, "
                        f"{row.get('stops', '')} stop(s), {duration_label(row.get('duration_minutes'))}"
                    ),
                    "return_detail": "",
                    "outbound_cell": (
                        f"{leg['origin']} -> {leg['destination']}\n{leg['date']}\n"
                        f"{row.get('depart_time', '')} -> {row.get('arrive_time', '')}\n"
                        f"{row.get('flight_numbers', '') or row.get('carriers', '')}, "
                        f"{row.get('stops', '')} stop(s), {duration_label(row.get('duration_minutes'))}"
                    )
                    if leg["direction"] == "outbound"
                    else "",
                    "return_cell": (
                        f"{leg['origin']} -> {leg['destination']}\n{leg['date']}\n"
                        f"{row.get('depart_time', '')} -> {row.get('arrive_time', '')}\n"
                        f"{row.get('flight_numbers', '') or row.get('carriers', '')}, "
                        f"{row.get('stops', '')} stop(s), {duration_label(row.get('duration_minutes'))}"
                    )
                    if leg["direction"] == "return"
                    else "",
                    "source_status": "ok",
                    "raw": row,
                    "leg": leg,
                }
            )
    return sorted(rows, key=lambda row: (row["score"], row["effective_num"], row["duration_minutes"]))


def duration_label(value: Any) -> str:
    if value in (None, ""):
        return ""
    minutes = int(value)
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def paired_open_jaw(outbound: dict[str, Any], return_row: dict[str, Any]) -> bool:
    return (
        outbound["leg"]["origin"] != return_row["leg"]["destination"]
        or outbound["leg"]["destination"] != return_row["leg"]["origin"]
    )


def award_pair_rows(award_rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    outbound_rows = [row for row in award_rows if row["direction"] == "outbound"]
    return_rows = [row for row in award_rows if row["direction"] == "return"]
    pairs = []
    for outbound in outbound_rows:
        for return_row in return_rows:
            open_jaw = paired_open_jaw(outbound, return_row)
            score_value = outbound["score"] + return_row["score"]
            effective_value = outbound["effective_num"] + return_row["effective_num"]
            notes = short_notes(
                ", ".join(value for value in [outbound["notes"], return_row["notes"]] if value),
                open_jaw=open_jaw,
            )
            notes = better_note(notes, "book as two separate awards")
            pairs.append(
                {
                    "kind": "award pair",
                    "route": f"{outbound['route']} / {return_row['route']}",
                    "dates": f"{outbound['dates']} / {return_row['dates']}",
                    "origin": outbound["leg"].get("origin", ""),
                    "destination": outbound["leg"].get("destination", ""),
                    "outbound_date": outbound["leg"].get("date", outbound["dates"]),
                    "return_origin": return_row["leg"].get("origin", ""),
                    "return_destination": return_row["leg"].get("destination", ""),
                    "return_date": return_row["leg"].get("date", return_row["dates"]),
                    "same_airports": not open_jaw,
                    "trip_type": "award pair",
                    "price": f"{outbound['price']} / {return_row['price']}",
                    "effective": compact_money(effective_value, "USD"),
                    "effective_num": effective_value,
                    "cpp": combined_cpp_label(outbound, return_row),
                    "cpp_num": combined_cpp_num(outbound, return_row),
                    "award_points": outbound.get("award_points", 0.0) + return_row.get("award_points", 0.0),
                    "award_components": combined_award_components(outbound, return_row),
                    "cash_component_usd": combined_cash_component(outbound, return_row),
                    "score": score_value,
                    "score_label": f"{score_value:.2f}",
                    "stop_penalty_base": outbound.get("stop_penalty_base", 0.0) + return_row.get("stop_penalty_base", 0.0),
                    "duration_penalty_base": outbound.get("duration_penalty_base", 0.0) + return_row.get("duration_penalty_base", 0.0),
                    "time_penalty_base": outbound.get("time_penalty_base", 0.0) + return_row.get("time_penalty_base", 0.0),
                    "next_day_penalty_base": outbound.get("next_day_penalty_base", 0.0) + return_row.get("next_day_penalty_base", 0.0),
                    "seat_credit_base": outbound.get("seat_credit_base", 0.0) + return_row.get("seat_credit_base", 0.0),
                    "stops": f"{outbound['stops']} + {return_row['stops']}",
                    "stops_num": outbound["stops_num"] + return_row["stops_num"],
                    "duration": duration_label(outbound["duration_minutes"] + return_row["duration_minutes"]),
                    "duration_minutes": outbound["duration_minutes"] + return_row["duration_minutes"],
                    "depart": f"{outbound['depart']} / {return_row['depart']}",
                    "arrive": f"{outbound['arrive']} / {return_row['arrive']}",
                    "outbound_depart": outbound["depart"],
                    "outbound_arrive": outbound["arrive"],
                    "return_depart": return_row["depart"],
                    "return_arrive": return_row["arrive"],
                    "provider": f"{outbound['provider']} / {return_row['provider']}",
                    "notes": notes,
                    "outbound_detail": outbound.get("outbound_detail", outbound["route"]),
                    "return_detail": return_row.get("outbound_detail", return_row["route"]),
                    "outbound_cell": outbound.get("outbound_cell") or outbound.get("outbound_detail", outbound["route"]),
                    "return_cell": return_row.get("return_cell") or return_row.get("outbound_detail", return_row["route"]),
                    "source_status": "ok",
                }
            )
    return sorted(deduplicate_rows(pairs), key=lambda row: (row["score"], row["effective_num"], row["stops_num"]))[:limit]


def cash_one_way_pair_rows(cash_leg_rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    outbound_rows = [row for row in cash_leg_rows if row["direction"] == "outbound"]
    return_rows = [row for row in cash_leg_rows if row["direction"] == "return"]
    pairs = []
    for outbound in outbound_rows:
        for return_row in return_rows:
            open_jaw = paired_open_jaw(outbound, return_row)
            score_value = outbound["score"] + return_row["score"]
            effective_value = outbound["effective_num"] + return_row["effective_num"]
            notes = short_notes(
                ", ".join(value for value in [outbound["notes"], return_row["notes"]] if value),
                open_jaw=open_jaw,
            )
            notes = better_note(notes, "book as two separate paid one-way tickets")
            notes = better_note(notes, "compare against real round-trip/open-jaw cash fare")
            pairs.append(
                {
                    "kind": "cash one-ways",
                    "route": f"{outbound['route']} / {return_row['route']}",
                    "dates": f"{outbound['dates']} / {return_row['dates']}",
                    "origin": outbound["leg"].get("origin", ""),
                    "destination": outbound["leg"].get("destination", ""),
                    "outbound_date": outbound["leg"].get("date", outbound["dates"]),
                    "return_origin": return_row["leg"].get("origin", ""),
                    "return_destination": return_row["leg"].get("destination", ""),
                    "return_date": return_row["leg"].get("date", return_row["dates"]),
                    "same_airports": not open_jaw,
                    "trip_type": "two one-ways",
                    "price": f"{outbound['price']} / {return_row['price']}",
                    "effective": compact_money(effective_value, "USD"),
                    "effective_num": effective_value,
                    "cpp": "",
                    "cpp_num": 0.0,
                    "award_points": 0.0,
                    "award_components": [],
                    "cash_component_usd": effective_value,
                    "score": score_value,
                    "score_label": f"{score_value:.2f}",
                    "stop_penalty_base": outbound.get("stop_penalty_base", 0.0) + return_row.get("stop_penalty_base", 0.0),
                    "duration_penalty_base": outbound.get("duration_penalty_base", 0.0) + return_row.get("duration_penalty_base", 0.0),
                    "time_penalty_base": outbound.get("time_penalty_base", 0.0) + return_row.get("time_penalty_base", 0.0),
                    "next_day_penalty_base": outbound.get("next_day_penalty_base", 0.0) + return_row.get("next_day_penalty_base", 0.0),
                    "seat_credit_base": outbound.get("seat_credit_base", 0.0) + return_row.get("seat_credit_base", 0.0),
                    "stops": f"{outbound['stops']} + {return_row['stops']}",
                    "stops_num": outbound["stops_num"] + return_row["stops_num"],
                    "duration": duration_label(outbound["duration_minutes"] + return_row["duration_minutes"]),
                    "duration_minutes": outbound["duration_minutes"] + return_row["duration_minutes"],
                    "depart": f"{outbound['depart']} / {return_row['depart']}",
                    "arrive": f"{outbound['arrive']} / {return_row['arrive']}",
                    "outbound_depart": outbound["depart"],
                    "outbound_arrive": outbound["arrive"],
                    "return_depart": return_row["depart"],
                    "return_arrive": return_row["arrive"],
                    "provider": "cash / cash",
                    "notes": notes,
                    "outbound_detail": outbound.get("outbound_detail", outbound["route"]),
                    "return_detail": return_row.get("return_detail", return_row["route"]),
                    "outbound_cell": outbound.get("outbound_cell") or outbound.get("outbound_detail", outbound["route"]),
                    "return_cell": return_row.get("return_cell") or return_row.get("return_detail", return_row["route"]),
                    "source_status": "ok",
                }
            )
    return sorted(deduplicate_rows(pairs), key=lambda row: (row["score"], row["effective_num"], row["stops_num"]))[:limit]


def paid_cash_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("origin", ""),
        row.get("destination", ""),
        row.get("outbound_date", ""),
        row.get("return_origin", ""),
        row.get("return_destination", ""),
        row.get("return_date", ""),
    )


def annotate_cash_strategy_comparisons(
    cash_rows: list[dict[str, Any]],
    cash_one_way_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    best_two_leg_by_trip = best_by_signature(cash_rows)
    best_one_way_by_trip = best_by_signature(cash_one_way_rows)

    annotated_cash = [
        annotate_paid_cash_row(row, best_one_way_by_trip.get(paid_cash_signature(row)), row_kind="two_leg")
        for row in cash_rows
    ]
    annotated_one_ways = [
        annotate_paid_cash_row(row, best_two_leg_by_trip.get(paid_cash_signature(row)), row_kind="one_way_pair")
        for row in cash_one_way_rows
    ]
    return annotated_cash, annotated_one_ways


def best_by_signature(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = paid_cash_signature(row)
        current = best.get(key)
        if current is None or (row["effective_num"], row["score"]) < (current["effective_num"], current["score"]):
            best[key] = row
    return best


def annotate_paid_cash_row(
    row: dict[str, Any],
    comparison: dict[str, Any] | None,
    *,
    row_kind: str,
) -> dict[str, Any]:
    annotated = dict(row)
    if comparison is None:
        annotated["cash_strategy_comparison"] = "no_exact_match"
        if row_kind == "one_way_pair":
            annotated["cash_flex_recommended"] = False
            annotated["notes"] = better_note(annotated.get("notes", ""), "no exact same-trip two-leg cash fare to compare")
        return annotated

    delta = float(row["effective_num"]) - float(comparison["effective_num"])
    annotated["cash_strategy_comparison_price"] = comparison.get("effective", "")
    annotated["cash_strategy_delta_usd"] = round(delta, 2)
    if abs(delta) <= CASH_PRICE_TOLERANCE_USD:
        annotated["cash_strategy_comparison"] = "same_price"
        if row_kind == "one_way_pair":
            annotated["cash_flex_recommended"] = True
            annotated["notes"] = better_note(
                annotated.get("notes", ""),
                "same price as true two-leg fare; more flexible",
            )
        else:
            annotated["notes"] = better_note(
                annotated.get("notes", ""),
                "two one-ways are same price and more flexible",
            )
        return annotated

    if delta < 0:
        annotated["cash_strategy_comparison"] = "cheaper"
        if row_kind == "one_way_pair":
            annotated["cash_flex_recommended"] = True
            annotated["notes"] = better_note(
                annotated.get("notes", ""),
                f"cheaper than true two-leg fare by {signed_money_delta(delta)}",
            )
        else:
            annotated["notes"] = better_note(
                annotated.get("notes", ""),
                f"cheaper than comparable two one-ways by {signed_money_delta(delta)}",
            )
        return annotated

    annotated["cash_strategy_comparison"] = "more_expensive"
    annotated["cash_flex_recommended"] = False
    if row_kind == "one_way_pair":
        annotated["notes"] = better_note(
            annotated.get("notes", ""),
            f"costs {signed_money_delta(delta)} more than true two-leg fare",
        )
    else:
        annotated["notes"] = better_note(
            annotated.get("notes", ""),
            f"comparable two one-ways cost {signed_money_delta(delta)} less",
        )
    return annotated


def mixed_cash_award_rows(
    cash_leg_rows: list[dict[str, Any]],
    award_rows: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    mixed_rows = []
    cash_outbound_rows = [row for row in cash_leg_rows if row["direction"] == "outbound"]
    cash_return_rows = [row for row in cash_leg_rows if row["direction"] == "return"]
    award_outbound_rows = [row for row in award_rows if row["direction"] == "outbound"]
    award_return_rows = [row for row in award_rows if row["direction"] == "return"]

    for outbound in cash_outbound_rows:
        for return_row in award_return_rows:
            mixed_rows.append(mixed_pair_row(outbound, return_row, outbound_kind="cash", return_kind="award"))

    for outbound in award_outbound_rows:
        for return_row in cash_return_rows:
            mixed_rows.append(mixed_pair_row(outbound, return_row, outbound_kind="award", return_kind="cash"))

    return sorted(deduplicate_rows(mixed_rows), key=lambda row: (row["score"], row["effective_num"], row["stops_num"]))[:limit]


def mixed_pair_row(
    outbound: dict[str, Any],
    return_row: dict[str, Any],
    *,
    outbound_kind: str,
    return_kind: str,
) -> dict[str, Any]:
    open_jaw = paired_open_jaw(outbound, return_row)
    score_value = outbound["score"] + return_row["score"]
    effective_value = outbound["effective_num"] + return_row["effective_num"]
    notes = short_notes(
        ", ".join(value for value in [outbound["notes"], return_row["notes"]] if value),
        open_jaw=open_jaw,
    )
    notes = better_note(notes, f"book {outbound_kind} outbound and {return_kind} return separately")
    return {
        "kind": "cash + award",
        "route": f"{outbound['route']} / {return_row['route']}",
        "dates": f"{outbound['dates']} / {return_row['dates']}",
        "origin": outbound["leg"].get("origin", ""),
        "destination": outbound["leg"].get("destination", ""),
        "outbound_date": outbound["leg"].get("date", outbound["dates"]),
        "return_origin": return_row["leg"].get("origin", ""),
        "return_destination": return_row["leg"].get("destination", ""),
        "return_date": return_row["leg"].get("date", return_row["dates"]),
        "same_airports": not open_jaw,
        "trip_type": "mixed cash-award",
        "price": f"{outbound_price_label(outbound, outbound_kind)} / {outbound_price_label(return_row, return_kind)}",
        "effective": compact_money(effective_value, "USD"),
        "effective_num": effective_value,
        "cpp": combined_cpp_label(outbound, return_row),
        "cpp_num": combined_cpp_num(outbound, return_row),
        "award_points": outbound.get("award_points", 0.0) + return_row.get("award_points", 0.0),
        "award_components": combined_award_components(outbound, return_row),
        "cash_component_usd": combined_cash_component(outbound, return_row),
        "score": score_value,
        "score_label": f"{score_value:.2f}",
        "stop_penalty_base": outbound.get("stop_penalty_base", 0.0) + return_row.get("stop_penalty_base", 0.0),
        "duration_penalty_base": outbound.get("duration_penalty_base", 0.0) + return_row.get("duration_penalty_base", 0.0),
        "time_penalty_base": outbound.get("time_penalty_base", 0.0) + return_row.get("time_penalty_base", 0.0),
        "next_day_penalty_base": outbound.get("next_day_penalty_base", 0.0) + return_row.get("next_day_penalty_base", 0.0),
        "seat_credit_base": outbound.get("seat_credit_base", 0.0) + return_row.get("seat_credit_base", 0.0),
        "stops": f"{outbound['stops']} + {return_row['stops']}",
        "stops_num": outbound["stops_num"] + return_row["stops_num"],
        "duration": duration_label(outbound["duration_minutes"] + return_row["duration_minutes"]),
        "duration_minutes": outbound["duration_minutes"] + return_row["duration_minutes"],
        "depart": f"{outbound['depart']} / {return_row['depart']}",
        "arrive": f"{outbound['arrive']} / {return_row['arrive']}",
        "outbound_depart": outbound["depart"],
        "outbound_arrive": outbound["arrive"],
        "return_depart": return_row["depart"],
        "return_arrive": return_row["arrive"],
        "provider": f"{outbound['provider']} / {return_row['provider']}",
        "notes": notes,
        "outbound_detail": outbound.get("outbound_detail") or outbound.get("outbound_cell") or outbound["route"],
        "return_detail": return_row.get("return_detail") or return_row.get("outbound_detail") or return_row["route"],
        "outbound_cell": outbound.get("outbound_cell") or outbound.get("outbound_detail") or outbound["route"],
        "return_cell": return_row.get("return_cell") or return_row.get("outbound_detail") or return_row["route"],
        "source_status": "ok",
    }


def outbound_price_label(row: dict[str, Any], kind: str) -> str:
    if kind == "cash":
        return f"Cash {row['price']}"
    return row["price"]


def deduplicate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for row in rows:
        key = (
            row.get("kind"),
            row.get("route"),
            row.get("dates"),
            row.get("price"),
            row.get("depart"),
            row.get("arrive"),
            row.get("score_label"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def has_late_penalty(row: dict[str, Any]) -> bool:
    notes = str(row.get("notes", "")).lower()
    return "late arrival" in notes or "after-midnight" in notes or "next day" in notes or "next_day" in notes


def has_complete_timing(row: dict[str, Any]) -> bool:
    if row.get("kind") == "cash":
        return row.get("cash_detail_status") == "complete"
    if row.get("kind") in {"award pair", "cash + award", "cash one-ways"}:
        return bool(row.get("outbound_depart") and row.get("return_depart"))
    return bool(row.get("depart"))


def cash_return_unverified(row: dict[str, Any]) -> bool:
    return row.get("kind") == "cash" and row.get("cash_detail_status") != "complete"


def excessive_duration(row: dict[str, Any]) -> bool:
    return numeric(row.get("duration_minutes"), 0) > 14 * 60


def recommendation_row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("kind"),
        row.get("route"),
        row.get("dates"),
        row.get("price"),
        row.get("depart"),
        row.get("arrive"),
        row.get("score_label"),
    )


def recommendation_cards(complete_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not complete_rows:
        return []

    cards = []
    cash_rows = [row for row in complete_rows if row["kind"] == "cash"]
    award_rows = [row for row in complete_rows if row["kind"] == "award pair"]
    mixed_rows = [row for row in complete_rows if row["kind"] == "cash + award"]
    cash_one_way_rows = [row for row in complete_rows if row["kind"] == "cash one-ways"]
    paid_cash_rows = [*cash_rows, *cash_one_way_rows]
    complete_timing_rows = [row for row in complete_rows if has_complete_timing(row)]
    overall_pool = complete_timing_rows or complete_rows
    best_overall = min(overall_pool, key=lambda row: (row["score"], row["effective_num"]))
    cards.append({"label": "Best overall", "row": best_overall})

    if paid_cash_rows:
        best_cash = min(
            paid_cash_rows,
            key=lambda row: (
                row["effective_num"],
                not bool(row.get("cash_flex_recommended")),
                row.get("kind") != "cash one-ways",
                row["score"],
            ),
        )
        cash_label = "Best cash price"
        if best_cash.get("kind") == "cash one-ways" and best_cash.get("cash_flex_recommended"):
            cash_label = "Suggested cash: two one-ways"
        elif cash_return_unverified(best_cash):
            cash_label = "Best priced cash, return unverified"
        cards.append({"label": cash_label, "row": best_cash})

    if award_rows:
        cards.append({"label": "Best award", "row": min(award_rows, key=lambda row: (row["score"], row["effective_num"]))})

    if mixed_rows:
        cards.append({"label": "Best cash + award", "row": min(mixed_rows, key=lambda row: (row["score"], row["effective_num"]))})

    if cash_one_way_rows:
        flexible_one_way_rows = [row for row in cash_one_way_rows if row.get("cash_flex_recommended")]
        one_way_label = "Suggested two one-ways" if flexible_one_way_rows else "Two one-ways comparator"
        cards.append(
            {
                "label": one_way_label,
                "row": min(flexible_one_way_rows or cash_one_way_rows, key=lambda row: (row["effective_num"], row["score"])),
            }
        )

    cheapest = min(complete_rows, key=lambda row: (row["effective_num"], row["score"]))
    cheapest_label = "Cheapest priced cash" if cash_return_unverified(cheapest) else "Cheapest tolerable"
    cards.append({"label": cheapest_label, "row": cheapest})
    cards.append(
        {
            "label": "Most convenient",
            "row": min(
                complete_timing_rows or complete_rows,
                key=lambda row: (
                    not has_complete_timing(row),
                    excessive_duration(row),
                    has_late_penalty(row),
                    row["stops_num"],
                    row["duration_minutes"],
                    not bool(row.get("same_airports")),
                    row["score"],
                ),
            ),
        }
    )

    deduped = []
    by_row: dict[tuple[Any, ...], dict[str, Any]] = {}
    for card in cards:
        key = recommendation_row_key(card["row"])
        if key in by_row:
            by_row[key]["labels"].append(card["label"])
        else:
            by_row[key] = {"labels": [card["label"]], "row": card["row"]}
            deduped.append(by_row[key])
    return [{"label": compact_card_label(card["labels"]), "row": card["row"]} for card in deduped]


def compact_card_label(labels: list[str]) -> str:
    priority = [
        "Suggested cash: two one-ways",
        "Best overall",
        "Best priced cash, return unverified",
        "Best cash price",
        "Best award",
        "Best cash + award",
        "Suggested two one-ways",
        "Two one-ways comparator",
        "Most convenient",
        "Cheapest tolerable",
        "Cheapest priced cash",
    ]
    for label in priority:
        if label in labels:
            return label
    return labels[0] if labels else ""


def write_master_json(
    path: Path,
    *,
    plan: TripSearchPlan,
    award_runs: list[dict[str, Any]],
    cash_runs: list[dict[str, Any]],
    cash_one_way_runs: list[dict[str, Any]],
    complete_rows: list[dict[str, Any]],
    award_rows: list[dict[str, Any]],
    cash_one_way_rows: list[dict[str, Any]],
) -> None:
    payload = {
        "plan": {
            "outbound_legs": [asdict(leg) for leg in plan.outbound_legs],
            "return_legs": [asdict(leg) for leg in plan.return_legs],
            "cash_one_way_legs": [asdict(leg) for leg in plan.cash_one_way_legs],
            "cash_itineraries": [itinerary_payload(itinerary) for itinerary in plan.cash_itineraries],
        },
        "runs": {
            "award": [summary_run(run) for run in award_runs],
            "cash": [summary_run(run) for run in cash_runs],
            "cash_one_way": [summary_run(run) for run in cash_one_way_runs],
        },
        "rows": {
            "complete_plans": [{key: value for key, value in row.items() if key not in {"raw", "leg"}} for row in complete_rows],
            "award_legs": [{key: value for key, value in row.items() if key not in {"raw", "leg"}} for row in award_rows],
            "cash_one_way_legs": [{key: value for key, value in row.items() if key not in {"raw", "leg"}} for row in cash_one_way_rows],
        },
    }
    write_json(path, payload)


def summary_run(run: dict[str, Any]) -> dict[str, Any]:
    summary = dict(run.get("summary") or {})
    if summary.get("provider_error"):
        summary["provider_error"] = compact_error(summary["provider_error"])
    return {
        key: value
        for key, value in {
            "leg": run.get("leg"),
            "cash_leg": run.get("cash_leg"),
            "itinerary": run.get("itinerary"),
            "summary": summary,
            "error": compact_error(run.get("error")),
        }.items()
        if value not in (None, "")
    }


def unique_options(rows: list[dict[str, Any]], key: str) -> str:
    values = sorted({str(row.get(key, "")) for row in rows if row.get(key, "") not in ("", None)})
    return "\n".join(f'<option value="{escape(value)}">{escape(value)}</option>' for value in values)


def row_badges(row: dict[str, Any]) -> list[str]:
    badges = []
    if row.get("kind") == "cash":
        status = str(row.get("cash_detail_status") or "")
        if status and status != "complete":
            badges.append("timing missing")
    if row.get("kind") == "cash one-ways":
        if row.get("cash_flex_recommended"):
            badges.append("flexible")
    if row.get("cash_strategy_comparison") == "same_price":
        badges.append("same price")
    elif row.get("cash_strategy_comparison") == "cheaper" and row.get("kind") == "cash one-ways":
        badges.append("cheaper")
    if has_late_penalty(row):
        badges.append("late")
    return [badge for badge in dict.fromkeys(badges) if badge]


def badges_html(row: dict[str, Any]) -> str:
    return "".join(f'<span class="badge">{escape(badge)}</span>' for badge in row_badges(row))


def multiline_cell(value: Any, *, muted: bool = False) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return '<span class="muted">-</span>'
    class_name = "leg-line muted" if muted else "leg-line"
    return "".join(f'<div class="{class_name}">{escape(line)}</div>' for line in lines)


def compact_route(row: dict[str, Any]) -> str:
    origin = str(row.get("origin") or "")
    destination = str(row.get("destination") or "")
    return_origin = str(row.get("return_origin") or "")
    return_destination = str(row.get("return_destination") or "")

    if not return_origin and not return_destination:
        return str(row.get("route") or "")
    if origin and destination and return_origin == destination and return_destination == origin:
        return f"{origin} <-> {destination}"
    if origin and destination and return_origin == destination and return_destination:
        return f"{origin} -> {destination} -> {return_destination}"
    if origin and destination and return_origin and return_destination:
        return f"{origin} -> {destination} / {return_origin} -> {return_destination}"
    return str(row.get("route") or "")


def compact_dates(row: dict[str, Any]) -> str:
    outbound_date = str(row.get("outbound_date") or "")
    return_date = str(row.get("return_date") or "")
    if outbound_date and return_date:
        return f"{outbound_date} -> {return_date}"
    return str(row.get("dates") or "")


def row_kind_label(row: dict[str, Any]) -> str:
    labels = {
        "cash": "Cash",
        "cash + award": "Cash+award",
        "cash one-ways": "2x cash",
        "award pair": "Award",
        "outbound cash": "Out cash",
        "return cash": "Ret cash",
        "outbound award": "Out award",
        "return award": "Ret award",
    }
    return labels.get(str(row.get("kind") or ""), str(row.get("kind") or ""))


def note_from_penalties(row: dict[str, Any]) -> list[str]:
    text = str(row.get("notes") or "").lower()
    notes = []
    if "next day" in text or "next_day" in text:
        notes.append("Next-day arrival")
    if "after-midnight" in text or "late arrival" in text:
        notes.append("Late arrival")
    if "very early departure" in text:
        notes.append("Very early departure")
    elif "early departure" in text:
        notes.append("Early departure")
    return notes


def display_notes(row: dict[str, Any]) -> str:
    notes = note_from_penalties(row)
    comparison = row.get("cash_strategy_comparison")
    delta = row.get("cash_strategy_delta_usd")
    if row.get("kind") == "cash":
        if comparison == "cheaper" and delta not in ("", None):
            notes.append(f"Saves {signed_money_delta(float(delta))} vs 2 one-ways")
        elif comparison == "same_price":
            notes.append("2 one-ways same price; more flexible")
        elif comparison == "more_expensive" and delta not in ("", None):
            notes.append(f"2 one-ways save {signed_money_delta(float(delta))}")
        if cash_return_unverified(row):
            notes.append("Return timing missing")
    elif row.get("kind") == "cash one-ways":
        if comparison == "cheaper" and delta not in ("", None):
            notes.append(f"Saves {signed_money_delta(float(delta))} vs two-leg cash")
        elif comparison == "same_price":
            notes.append("Same price as two-leg; more flexible")
        elif comparison == "more_expensive" and delta not in ("", None):
            notes.append(f"Costs {signed_money_delta(float(delta))} more than two-leg cash")
    return "; ".join(dict.fromkeys(note for note in notes if note))


def plan_cell(row: dict[str, Any]) -> str:
    route = escape(compact_route(row))
    dates = escape(compact_dates(row))
    badges = badges_html(row)
    badges_tag = f'<div class="badges">{badges}</div>' if badges else ""
    return f'<div class="plan-route">{route}</div><div class="plan-dates">{dates}</div>{badges_tag}'


def score_defaults_from_preferences(preferences: dict[str, Any]) -> dict[str, Any]:
    ranking = preferences.get("ranking", {})
    return {
        "stopPenalty": float(ranking.get("stop_penalty_usd", 50)),
        "durationPenalty": float(ranking.get("duration_penalty_usd_per_hour", 5)),
        "timePenaltyDefaults": hourly_time_defaults(preferences),
    }


def script_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True).replace("</", "<\\/")


def row_data_attrs(row: dict[str, Any], *, section: str) -> str:
    outbound_label = str(row.get("outbound_cell") or row.get("outbound_detail") or row.get("depart") or "")
    return_label = str(row.get("return_cell") or row.get("return_detail") or row.get("arrive") or "")
    attrs = {
        "section": section,
        "kind": row.get("kind", ""),
        "trip-type": row.get("trip_type", ""),
        "route": row.get("route", ""),
        "dates": row.get("dates", ""),
        "origin": row.get("origin", ""),
        "destination": row.get("destination", ""),
        "outbound-date": row.get("outbound_date", ""),
        "return-date": row.get("return_date", ""),
        "outbound-key": outbound_label,
        "return-key": return_label,
        "outbound-label": outbound_label,
        "return-label": return_label,
        "same-airports": str(bool(row.get("same_airports"))).lower(),
        "late": str(has_late_penalty(row)).lower(),
        "score": row.get("score", ""),
        "original-score": row.get("score", ""),
        "effective": row.get("effective_num", ""),
        "cpp": row.get("cpp", ""),
        "cpp-num": row.get("cpp_num", ""),
        "cash-component": component_value(row.get("cash_component_usd", row.get("effective_num"))),
        "award-components": json.dumps(row.get("award_components") or [], ensure_ascii=True, sort_keys=True),
        "time-hours": json.dumps(time_hour_counts(row), ensure_ascii=True),
        "stops": row.get("stops_num", ""),
        "duration": row.get("duration_minutes", ""),
        "stop-penalty": component_value(row.get("stop_penalty_base")),
        "duration-penalty": component_value(row.get("duration_penalty_base")),
    }
    return " ".join(
        f'data-{name}="{escape(str(value), quote=True)}"'
        for name, value in attrs.items()
    )


def flight_result_cards(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty-results">No complete plans matched the current filters.</div>'

    tags = []
    for index, row in enumerate(rows, start=1):
        note_text = display_notes(row)
        notes = f'<p class="card-note">{escape(note_text)}</p>' if note_text else ""
        badges = badges_html(row)
        badges_tag = f'<div class="badges">{badges}</div>' if badges else ""
        original_score = escape(str(row.get("score_label") or ""))
        price_line = escape(str(row.get("price") or ""))
        effective_line = escape(str(row.get("effective") or ""))
        provider = escape(str(row.get("provider") or ""))
        kind = escape(row_kind_label(row))
        attrs = row_data_attrs(row, section="complete")
        tags.append(
            f'<article class="trip-card" {attrs}>'
            '<div class="card-main">'
            '<div class="card-route">'
            f'<span class="result-index">#{index}</span>'
            f'<span class="pill">{kind}</span>'
            f'<h2>{escape(compact_route(row))}</h2>'
            f'<p>{escape(compact_dates(row))}</p>'
            f'{badges_tag}'
            '</div>'
            '<div class="card-price">'
            f'<strong>{price_line}</strong>'
            f'<span><span data-live-effective>{effective_line}</span> effective</span>'
            f'<span>{provider}</span>'
            '</div>'
            '<div class="card-score">'
            '<span>Adjusted Score</span>'
            f'<strong data-live-score>{original_score}</strong>'
            f'<small>Agent {original_score}</small>'
            '</div>'
            '</div>'
            '<div class="card-legs">'
            f'<div><span>Outbound</span>{multiline_cell(row.get("outbound_cell") or row.get("outbound_detail") or row.get("depart"))}</div>'
            f'<div><span>Return</span>{multiline_cell(row.get("return_cell") or row.get("return_detail") or row.get("arrive"), muted=not bool(row.get("return_depart") or row.get("return_detail") or row.get("return_cell")))}</div>'
            '</div>'
            f'{notes}'
            '<div class="card-actions">'
            '<button type="button" data-toggle-details>Details</button>'
            '<label class="compare-check"><input type="checkbox" data-compare-plan> Compare details</label>'
            '</div>'
            '<div class="card-details" hidden>'
            '<div class="score-breakdown" data-breakdown></div>'
            f'<p>{escape(str(row.get("notes") or ""))}</p>'
            '</div>'
            '</article>'
        )
    return "\n".join(tags)


def table_rows(rows: list[dict[str, Any]], *, section: str) -> str:
    tags = []
    for row in rows:
        note_text = display_notes(row)
        note_html = escape(note_text) if note_text else '<span class="muted">-</span>'
        tags.append(
            "<tr "
            f'{row_data_attrs(row, section=section)}>'
            f'<td><span class="pill">{escape(row_kind_label(row))}</span></td>'
            f'<td class="route">{plan_cell(row)}</td>'
            f'<td class="leg-cell">{multiline_cell(row.get("outbound_cell") or row.get("outbound_detail") or row.get("depart"))}</td>'
            f'<td class="leg-cell">{multiline_cell(row.get("return_cell") or row.get("return_detail") or row.get("arrive"), muted=not bool(row.get("return_depart") or row.get("return_detail") or row.get("return_cell")))}</td>'
            f'<td>{escape(row["price"])}</td>'
            f'<td data-sort="{row["effective_num"]}" data-live-effective>{escape(row["effective"])}</td>'
            f'<td class="score-value" data-sort="{row["score"]}" data-live-score>{escape(row["score_label"])}</td>'
            f'<td data-sort="{row["stops_num"]}">{escape(str(row["stops"]))}</td>'
            f'<td data-sort="{row["duration_minutes"]}">{escape(row["duration"])}</td>'
            f'<td class="notes">{note_html}</td>'
            "</tr>"
        )
    return "\n".join(tags)


def recommendation_leg_html(label: str, value: Any, *, muted: bool = False) -> str:
    return (
        '<div class="rec-leg">'
        f'<span>{escape(label)}</span>'
        f'{multiline_cell(value, muted=muted)}'
        '</div>'
    )


def write_master_html(
    path: Path,
    *,
    title: str,
    cabin: str,
    plan: TripSearchPlan,
    complete_rows: list[dict[str, Any]],
    award_rows: list[dict[str, Any]],
    cash_one_way_rows: list[dict[str, Any]],
    errors: list[str],
    preferences_path: Path = DEFAULT_PREFERENCES_PATH,
    data_mode: str = "cached allowed",
) -> None:
    all_rows = [*complete_rows, *award_rows, *cash_one_way_rows]
    cash_priced = len([row for row in complete_rows if row["kind"] == "cash"])
    mixed_priced = len([row for row in complete_rows if row["kind"] == "cash + award"])
    cash_one_way_pairs = len([row for row in complete_rows if row["kind"] == "cash one-ways"])
    one_way_cash_options = len(cash_one_way_rows)
    one_way_cash_routes_priced = len(
        {
            (row.get("direction"), row.get("route"), row.get("dates"))
            for row in cash_one_way_rows
        }
    )
    cash_detail_complete = len(
        [row for row in complete_rows if row["kind"] == "cash" and row.get("cash_detail_status") == "complete"]
    )
    cash_detail_label = f"{cash_detail_complete}/{cash_priced}" if cash_priced else "No priced cash fares"
    award_pairs = len([row for row in complete_rows if row["kind"] == "award pair"])
    cash_failures = len([error for error in errors if error.startswith("Cash ")])
    award_failures = len(errors) - cash_failures
    cards = recommendation_cards(complete_rows)
    card_tags = []
    for card in cards:
        row = card["row"]
        card_note = display_notes(row)
        card_badges = badges_html(row)
        card_badges_tag = f'<div class="badges rec-badges">{card_badges}</div>' if card_badges else ""
        card_note_tag = f'<em>{escape(card_note)}</em>' if card_note else ""
        if cash_return_unverified(row):
            timing_prefix = "Return timing unverified · "
        else:
            timing_prefix = ""
        card_tags.append(
            f'<article class="recommendation" {row_data_attrs(row, section="summary")}>'
            f'<span>{escape(card["label"])}</span>'
            f'<h2>{escape(compact_route(row))}</h2>'
            f'<p>{escape(compact_dates(row))}</p>'
            f'{card_badges_tag}'
            '<div class="rec-legs">'
            f'{recommendation_leg_html("Outbound", row.get("outbound_cell") or row.get("outbound_detail") or row.get("depart"))}'
            f'{recommendation_leg_html("Return", row.get("return_cell") or row.get("return_detail") or row.get("arrive"), muted=row.get("kind") == "cash" and row.get("cash_detail_status") != "complete")}'
            '</div>'
            f'<strong>{escape(timing_prefix)}{escape(row["price"])} · <span data-live-effective>{escape(row["effective"])}</span> effective · score <span data-live-score>{escape(row["score_label"])}</span></strong>'
            f'{card_note_tag}'
            "</article>"
        )
    if complete_rows and not any(row["kind"] == "cash" for row in complete_rows):
        card_tags.append(
            '<article class="recommendation">'
            '<span>Cash unavailable</span>'
            '<h2>No paid fare parsed</h2>'
            f'<p>{len(plan.cash_itineraries)} cash itineraries checked</p>'
            '<strong>See partial results</strong>'
            '<em>The cash provider did not return parseable round-trip or open-jaw fares for this search.</em>'
            "</article>"
        )
    if complete_rows and not any(row["kind"] == "award pair" for row in complete_rows):
        card_tags.append(
            '<article class="recommendation">'
            '<span>Award unavailable</span>'
            '<h2>No complete award pair</h2>'
            f'<p>{len(plan.outbound_legs)} outbound and {len(plan.return_legs)} return award legs checked</p>'
            '<strong>See award detail tables</strong>'
            '<em>The award side did not produce both outbound and return options for a complete suggested pair.</em>'
            "</article>"
        )
    if one_way_cash_options == 0:
        card_tags.append(
            '<article class="recommendation">'
            '<span>Mixed plans unavailable</span>'
            '<h2>No one-way cash options parsed</h2>'
            f'<p>{len(plan.cash_one_way_legs)} one-way cash legs checked</p>'
            '<strong>Cash+award plans need one-way cash pricing</strong>'
            '<em>The report still compares true two-leg cash and award pairs when available.</em>'
            "</article>"
        )

    preferences = load_preferences(preferences_path)
    score_defaults = score_defaults_from_preferences(preferences)
    point_controls = point_value_controls(all_rows)
    score_config_json = script_json({"scoreDefaults": score_defaults})
    error_tags = "".join(f"<li>{escape(error)}</li>" for error in errors)
    cash_issue_text = f"; {cash_failures} no-result/provider issues" if cash_failures else ""
    award_issue_text = f"; {award_failures} award issues" if award_failures else ""
    error_summary = (
        f"Cash: {cash_priced}/{len(plan.cash_itineraries)} two-leg paid fares priced; "
        f"{one_way_cash_routes_priced}/{len(plan.cash_one_way_legs)} one-way cash routes priced{cash_issue_text}. "
        f"Awards: {award_pairs} complete award pair(s){award_issue_text}."
    )
    cash_quality = (
        f"Cash details: {cash_detail_complete}/{cash_priced} priced fares have verified return timing."
        if cash_priced
        else "Cash details: no paid fares were priced, so no cash return timing could be verified."
    )
    quality_summary = (
        f"Data mode: {data_mode}. {cash_quality} One-way cash legs priced: "
        f"{one_way_cash_routes_priced}/{len(plan.cash_one_way_legs)}; one-way cash options shown: {one_way_cash_options}; "
        f"mixed cash+award plans: {mixed_priced}. "
        f"Award legs shown: {len(award_rows)}. Provider issues: {len(errors)}."
    )
    complete_tags = table_rows(complete_rows, section="complete")
    outbound_tags = table_rows([row for row in award_rows if row["direction"] == "outbound"], section="outbound")
    return_tags = table_rows([row for row in award_rows if row["direction"] == "return"], section="return")
    cash_one_way_tags = table_rows(cash_one_way_rows, section="cash-one-way")
    flight_cards = flight_result_cards(complete_rows)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17212b;
      --muted: #66717e;
      --line: #dbe3ea;
      --surface: #ffffff;
      --soft: #f5f8fb;
      --cash: #0f766e;
      --award: #7c3aed;
      --accent: #1d4e89;
      --warn: #9a3412;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #edf3f6;
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}
    header {{
      padding: 30px 32px 18px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }}
    .eyebrow {{
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 760;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      line-height: 1.2;
      font-weight: 780;
    }}
    main {{ padding: 22px 32px 36px; }}
    .stats, .recommendations {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .stat, .recommendation, .guide, .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .stat {{ padding: 14px 16px; }}
    .stat span, .recommendation span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
      text-transform: uppercase;
    }}
    .stat strong {{
      display: block;
      margin-top: 5px;
      font-size: 22px;
      line-height: 1.12;
      overflow-wrap: anywhere;
    }}
    .recommendation {{ padding: 15px 16px; }}
    .recommendation h2 {{
      margin: 7px 0 4px;
      font-size: 17px;
      line-height: 1.25;
    }}
    .recommendation p {{
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .recommendation strong, .recommendation em {{
      display: block;
      font-style: normal;
      font-size: 13px;
    }}
    .recommendation em {{
      margin-top: 5px;
      color: var(--muted);
      line-height: 1.35;
    }}
    .rec-badges {{ margin: 8px 0 10px; }}
    .rec-legs {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin: 8px 0 10px;
    }}
    .rec-leg {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: #fbfdff;
      min-width: 0;
    }}
    .rec-leg span {{
      margin-bottom: 5px;
    }}
    .guide {{
      margin-bottom: 18px;
      padding: 14px 16px;
      color: #354556;
      font-size: 14px;
      line-height: 1.45;
    }}
    .quality {{
      margin-bottom: 18px;
      padding: 12px 16px;
      border: 1px solid #bfdbfe;
      border-radius: 8px;
      background: #eff6ff;
      color: #1e3a5f;
      font-size: 14px;
      line-height: 1.4;
    }}
    .errors {{
      margin: 0 0 18px;
      padding: 12px 16px;
      border: 1px solid #fed7aa;
      border-radius: 8px;
      background: #fff7ed;
      color: var(--warn);
    }}
    .view-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 14px;
    }}
    .view-tabs button {{
      min-width: 118px;
      background: var(--surface);
    }}
    .view-panel[hidden] {{
      display: none;
    }}
    .global-controls {{
      margin: 0 0 14px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .global-controls summary {{
      cursor: pointer;
      padding: 13px 16px;
      color: var(--ink);
      font-size: 14px;
      font-weight: 780;
    }}
    .global-controls-inner {{
      display: grid;
      grid-template-columns: minmax(280px, 0.8fr) minmax(320px, 1.2fr);
      gap: 16px;
      padding: 0 16px 16px;
    }}
    .control-block {{
      display: grid;
      gap: 10px;
      min-width: 0;
    }}
    .control-block h2 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.25;
    }}
    .results-board h2 {{
      margin: 0;
      font-size: 17px;
      line-height: 1.25;
    }}
    .results-board p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }}
    .quick-tabs {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }}
    button,
    .compare-check {{
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 10px;
      background: #f8fafc;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      font-weight: 720;
      cursor: pointer;
    }}
    button.active {{
      border-color: var(--accent);
      background: #e8f1fb;
      color: #123c69;
    }}
    .score-lab {{
      display: grid;
      gap: 8px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
    }}
    .score-lab h2 {{
      margin-bottom: 2px;
    }}
    .knob-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 10px;
    }}
    .score-lab label {{
      gap: 3px;
    }}
    .score-lab label > span {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }}
    .score-lab output {{
      color: var(--ink);
      font-weight: 780;
      text-transform: none;
    }}
    input[type="range"] {{
      padding: 0;
      min-height: 20px;
      accent-color: var(--accent);
    }}
    .point-lab {{
      margin-top: 4px;
    }}
    .cpp-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 10px;
    }}
    .time-editor {{
      display: grid;
      gap: 8px;
      margin-top: 4px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
    }}
    .time-editor-header,
    .time-hour-controls {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }}
    .time-editor-header strong {{
      font-size: 13px;
    }}
    .time-penalty-plot {{
      display: grid;
      grid-template-columns: repeat(24, minmax(8px, 1fr));
      gap: 3px;
      height: 112px;
      align-items: end;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfdff;
      touch-action: none;
      user-select: none;
    }}
    .hour-bar {{
      min-width: 0;
      min-height: 0;
      height: 100%;
      padding: 0;
      display: flex;
      align-items: end;
      justify-content: center;
      border: 0;
      border-radius: 4px;
      background: transparent;
      cursor: pointer;
    }}
    .hour-bar span {{
      display: block;
      width: 100%;
      min-height: 4px;
      height: var(--bar-height);
      border-radius: 4px 4px 2px 2px;
      background: #9cc8ef;
    }}
    .hour-bar.active span {{
      background: var(--accent);
    }}
    .time-hour-controls {{
      display: grid;
      grid-template-columns: minmax(92px, 130px) minmax(0, 1fr);
    }}
    .unit-note {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      text-transform: none;
    }}
    .control-details {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}
    .control-details summary {{
      cursor: pointer;
      color: var(--ink);
      font-size: 13px;
      font-weight: 780;
      list-style-position: inside;
    }}
    .control-details .controls {{
      margin-top: 10px;
    }}
    .results-board {{
      min-width: 0;
    }}
    .result-toolbar {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(180px, 240px);
      gap: 12px;
      align-items: end;
      margin-bottom: 12px;
      padding: 14px 16px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .trip-results {{
      display: grid;
      gap: 12px;
    }}
    .trip-card {{
      display: grid;
      gap: 12px;
      padding: 15px 16px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .trip-card:hover {{
      border-color: #b7c7d6;
      box-shadow: 0 1px 5px rgba(15, 23, 42, 0.08);
    }}
    .trip-card.selected {{
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(29, 78, 137, 0.12);
    }}
    .card-main {{
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(160px, 0.75fr) minmax(130px, 0.55fr);
      gap: 14px;
      align-items: start;
    }}
    .card-route h2 {{
      margin: 7px 0 4px;
      font-size: 19px;
      line-height: 1.2;
    }}
    .card-route p,
    .card-note {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }}
    .result-index {{
      display: inline-block;
      margin-right: 7px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 780;
    }}
    .card-price,
    .card-score {{
      display: grid;
      gap: 3px;
      justify-items: end;
      text-align: right;
    }}
    .card-price strong,
    .card-score strong {{
      font-size: 22px;
      line-height: 1.05;
      overflow-wrap: anywhere;
    }}
    .card-price span,
    .card-score span,
    .card-score small {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.25;
    }}
    .card-legs {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }}
    .card-legs > div {{
      min-width: 0;
      padding: 10px 11px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfdff;
    }}
    .card-legs span {{
      display: block;
      margin-bottom: 5px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 780;
      text-transform: uppercase;
    }}
    .card-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}
    .compare-check {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      width: fit-content;
      text-transform: none;
    }}
    .compare-check input {{
      min-height: auto;
      width: auto;
      margin: 0;
    }}
    .card-details {{
      display: grid;
      gap: 8px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
      color: #405164;
      font-size: 13px;
      line-height: 1.4;
    }}
    .card-details[hidden] {{
      display: none;
    }}
    .score-breakdown {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .score-breakdown span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      background: #f8fafc;
      color: #334252;
      font-size: 12px;
      font-weight: 720;
    }}
    .compare-tray {{
      display: none;
      margin-bottom: 12px;
      padding: 12px 16px;
      border: 1px solid #bbf7d0;
      border-radius: 8px;
      background: #f0fdf4;
      color: #14532d;
      font-size: 13px;
    }}
    .compare-tray.active {{
      display: block;
    }}
    .compare-list {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-top: 8px;
    }}
    .compare-item {{
      display: grid;
      gap: 8px;
      border: 1px solid #86efac;
      border-radius: 8px;
      padding: 10px 11px;
      background: #ffffff;
    }}
    .compare-item h3 {{
      margin: 0;
      font-size: 15px;
      line-height: 1.25;
    }}
    .compare-item p {{
      margin: 0;
      color: #31553d;
      font-size: 12px;
      line-height: 1.35;
    }}
    .compare-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .compare-meta span {{
      border: 1px solid #dcfce7;
      border-radius: 999px;
      padding: 3px 8px;
      background: #f7fee7;
      color: #31553d;
      font-size: 12px;
      font-weight: 720;
    }}
    .compare-leg {{
      border-top: 1px solid #dcfce7;
      padding-top: 7px;
    }}
    .compare-leg strong {{
      display: block;
      margin-bottom: 3px;
      font-size: 11px;
      text-transform: uppercase;
      color: #166534;
    }}
    .compare-leg span {{
      display: block;
      color: #334252;
      font-size: 12px;
      line-height: 1.35;
    }}
    .empty-results {{
      padding: 18px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: #fbfdff;
      color: var(--muted);
      font-size: 14px;
    }}
    .builder {{
      display: grid;
      gap: 14px;
      margin-bottom: 18px;
    }}
    .builder-header {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(180px, 240px);
      gap: 12px;
      align-items: end;
      padding: 14px 16px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .builder-header h2 {{
      margin: 0;
      font-size: 18px;
    }}
    .builder-header p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }}
    .builder-grid {{
      display: grid;
      grid-template-columns: minmax(220px, 0.95fr) minmax(220px, 0.95fr) minmax(260px, 1.25fr);
      gap: 12px;
      align-items: start;
    }}
    .builder-column {{
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .builder-column h3 {{
      margin: 0;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      font-size: 15px;
      line-height: 1.2;
    }}
    .choice-list,
    .builder-results {{
      display: grid;
      gap: 8px;
      max-height: 640px;
      overflow: auto;
      padding: 10px;
    }}
    .leg-choice {{
      display: grid;
      gap: 4px;
      width: 100%;
      min-height: 0;
      text-align: left;
      background: #fbfdff;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
    }}
    .leg-choice.active {{
      border-color: var(--accent);
      background: #e8f1fb;
      color: #123c69;
    }}
    .leg-choice strong {{
      font-size: 13px;
      line-height: 1.25;
    }}
    .leg-choice span {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.25;
    }}
    .builder-card {{
      display: grid;
      gap: 8px;
      padding: 11px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    .builder-card h3 {{
      margin: 0;
      padding: 0;
      border: 0;
      font-size: 15px;
      line-height: 1.25;
    }}
    .builder-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .builder-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .builder-meta span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 7px;
      color: #334252;
      background: #f8fafc;
      font-size: 12px;
      font-weight: 720;
    }}
    .controls {{
      display: grid;
      grid-template-columns: minmax(220px, 2fr) repeat(4, minmax(140px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }}
    label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
      text-transform: uppercase;
    }}
    input, select {{
      min-height: 34px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 9px;
      background: var(--surface);
      color: var(--ink);
      font: inherit;
    }}
    .panel {{
      margin-top: 18px;
      overflow: hidden;
    }}
    .panel h2 {{
      margin: 0;
      padding: 15px 16px;
      border-bottom: 1px solid var(--line);
      font-size: 18px;
    }}
    .table-wrap {{ overflow: auto; }}
    table {{
      width: 100%;
      min-width: 1240px;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
      font-size: 14px;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8fafc;
      color: #334252;
      font-size: 12px;
      text-transform: uppercase;
      cursor: pointer;
    }}
    tbody tr:hover {{ background: var(--soft); }}
    td:nth-child(6), td:nth-child(7), td:nth-child(8), td:nth-child(9), td:nth-child(10) {{ text-align: right; }}
    .route {{ font-weight: 740; }}
    .plan-route {{
      margin-bottom: 5px;
      font-weight: 760;
    }}
    .plan-dates {{
      margin-bottom: 7px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 620;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 7px;
      background: #f8fafc;
      color: #334252;
      font-size: 11px;
      font-weight: 760;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .subleg {{
      display: block;
      color: #475569;
      font-size: 12px;
      line-height: 1.35;
      white-space: normal;
    }}
    .subleg span {{
      display: inline-block;
      min-width: 64px;
      color: var(--muted);
      font-weight: 760;
      text-transform: uppercase;
      font-size: 11px;
    }}
    .leg-cell {{
      min-width: 190px;
      white-space: normal;
      vertical-align: top;
    }}
    .leg-line {{
      color: #334252;
      font-size: 12px;
      line-height: 1.35;
      white-space: normal;
    }}
    .leg-line:first-child {{
      font-weight: 760;
      color: var(--ink);
    }}
    .muted {{
      color: var(--muted);
    }}
    .notes {{
      min-width: 260px;
      white-space: normal;
      color: var(--muted);
    }}
    .pill {{
      display: inline-flex;
      justify-content: center;
      min-width: 74px;
      border-radius: 999px;
      padding: 3px 8px;
      background: var(--accent);
      color: #fff;
      font-size: 12px;
      font-weight: 780;
      text-transform: uppercase;
    }}
    tr[data-kind="cash"] .pill,
    tr[data-kind="cash one-ways"] .pill,
    tr[data-kind$="cash"] .pill,
    .trip-card[data-kind="cash"] .pill,
    .trip-card[data-kind="cash one-ways"] .pill,
    .trip-card[data-kind$="cash"] .pill {{ background: var(--cash); }}
    tr[data-kind="cash + award"] .pill,
    .trip-card[data-kind="cash + award"] .pill {{ background: #be123c; }}
    tr[data-kind="award pair"] .pill,
    tr[data-kind$="award"] .pill,
    .trip-card[data-kind="award pair"] .pill,
    .trip-card[data-kind$="award"] .pill {{ background: var(--award); }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      .stats, .recommendations, .controls {{ grid-template-columns: 1fr 1fr; }}
      .global-controls-inner {{ grid-template-columns: 1fr; }}
      .builder-grid {{ grid-template-columns: 1fr; }}
      .builder-header {{ grid-template-columns: 1fr; }}
      .card-main {{ grid-template-columns: 1fr; }}
      .card-price, .card-score {{ justify-items: start; text-align: left; }}
      h1 {{ font-size: 24px; }}
    }}
    @media (max-width: 620px) {{
      .stats, .recommendations, .controls {{ grid-template-columns: 1fr; }}
      .rec-legs {{ grid-template-columns: 1fr; }}
      .quick-tabs, .result-toolbar, .card-legs, .cpp-grid, .time-hour-controls {{ grid-template-columns: 1fr; }}
      .time-penalty-plot {{ gap: 2px; padding: 6px; }}
    }}
  </style>
</head>
<body>
  <script id="score-config" type="application/json">{score_config_json}</script>
  <header>
    <p class="eyebrow">{escape(cabin)} · multi-airport trip search</p>
    <h1>{escape(title)}</h1>
  </header>
  <main>
    <nav class="view-tabs" aria-label="Report views">
      <button type="button" class="active" data-view-tab="summary">Summary</button>
      <button type="button" data-view-tab="plans">Plans</button>
      <button type="button" data-view-tab="build">Build Trip</button>
      <button type="button" data-view-tab="data">Data</button>
    </nav>
    <details class="global-controls">
      <summary>Trip Controls</summary>
      <div class="global-controls-inner">
        <section class="control-block" aria-label="Score knobs">
          <h2>Score Knobs</h2>
          <section class="score-lab">
            <div class="knob-grid">
              <label><span>Stops <output id="stopPenaltyValue"></output></span><input id="stopPenalty" type="range" min="0" max="200" step="5" value="{score_defaults["stopPenalty"]}"></label>
              <label><span>Duration/hr <output id="durationPenaltyValue"></output></span><input id="durationPenalty" type="range" min="0" max="40" step="1" value="{score_defaults["durationPenalty"]}"></label>
            </div>
            <div class="time-editor">
              <div class="time-editor-header"><strong>Bad Times Per Event</strong><output id="timePenaltySelectedValue"></output></div>
              <p class="unit-note">Applied once for each departure or arrival in that hour.</p>
              <div id="timePenaltyPlot" class="time-penalty-plot" aria-label="Hourly bad-time penalties"></div>
              <div class="time-hour-controls">
                <label>Hour<select id="timeHourSelect">{hour_options()}</select></label>
                <label><span>Penalty per event <output id="timeHourPenaltyValue"></output></span><input id="timeHourPenalty" type="range" min="0" max="200" step="5" value="0"></label>
              </div>
            </div>
          </section>
          {point_controls}
        </section>
        <section class="control-block" aria-label="Filters">
          <h2>Filters</h2>
          <label>Search<input id="search" type="search" placeholder="Airport, carrier, program, warning"></label>
          <div class="quick-tabs" role="group" aria-label="Quick plan filters">
            <button type="button" class="active" data-kind-preset="">All</button>
            <button type="button" data-kind-preset="cash">Cash</button>
            <button type="button" data-kind-preset="award pair">Award</button>
            <button type="button" data-kind-preset="cash + award">Mixed</button>
          </div>
          <details class="control-details">
            <summary>More filters</summary>
            <section class="controls" aria-label="More filters">
              <label>Kind<select id="kindFilter"><option value="">All</option><option value="cash">Cash</option><option value="cash + award">Cash + award</option><option value="cash one-ways">Cash one-ways</option><option value="award pair">Award pair</option><option value="outbound cash">Outbound cash</option><option value="return cash">Return cash</option><option value="outbound award">Outbound award</option><option value="return award">Return award</option></select></label>
              <label>Trip Type<select id="tripFilter"><option value="">All</option><option value="round-trip">Round trip</option><option value="multi-city">Multi-city</option><option value="mixed cash-award">Mixed cash-award</option><option value="two one-ways">Two one-ways</option><option value="award pair">Award pair</option><option value="cash one-way">Cash one-way</option><option value="award one-way">Award one-way</option></select></label>
              <label>Route Origin<select id="originFilter"><option value="">All</option>{unique_options(all_rows, "origin")}</select></label>
              <label>Route Destination<select id="destinationFilter"><option value="">All</option>{unique_options(all_rows, "destination")}</select></label>
              <label>Outbound Date<select id="outboundDateFilter"><option value="">All</option>{unique_options(all_rows, "outbound_date")}</select></label>
              <label>Return Date<select id="returnDateFilter"><option value="">All</option>{unique_options(all_rows, "return_date")}</select></label>
              <label>Max Score<input id="scoreFilter" type="number" min="0" step="1" placeholder="Any"></label>
              <label>Max Effective USD<input id="effectiveFilter" type="number" min="0" step="1" placeholder="Any"></label>
              <label>Max Stops<input id="stopsFilter" type="number" min="0" step="1" placeholder="Any"></label>
              <label>Late Arrival<select id="lateFilter"><option value="">All</option><option value="false">Hide late/overnight</option><option value="true">Only late/overnight</option></select></label>
            </section>
          </details>
        </section>
      </div>
    </details>
    <section id="summaryView" class="view-panel">
      <section class="summary-body">
        <section class="stats" aria-label="Search counts">
          <div class="stat"><span>Outbound Award Legs</span><strong>{len(plan.outbound_legs)}</strong></div>
          <div class="stat"><span>Return Award Legs</span><strong>{len(plan.return_legs)}</strong></div>
          <div class="stat"><span>Paid Fares Priced</span><strong>{cash_priced}/{len(plan.cash_itineraries)}</strong></div>
          <div class="stat"><span>One-Way Cash Routes</span><strong>{one_way_cash_routes_priced}/{len(plan.cash_one_way_legs)}</strong></div>
          <div class="stat"><span>One-Way Cash Options</span><strong>{one_way_cash_options}</strong></div>
          <div class="stat"><span>Mixed Plans</span><strong>{mixed_priced}</strong></div>
          <div class="stat"><span>Two One-Way Cash Plans</span><strong>{cash_one_way_pairs}</strong></div>
          <div class="stat"><span>Cash Details Verified</span><strong>{cash_detail_label}</strong></div>
          <div class="stat"><span>Award Rows Shown</span><strong>{len(award_rows)}</strong></div>
          <div class="stat"><span>Complete Plans</span><strong>{len(complete_rows)}</strong></div>
        </section>
        <section class="recommendations" aria-label="Recommendations">
          {"".join(card_tags) if card_tags else '<article class="recommendation"><span>No complete plans</span><h2>Refresh data or check provider errors</h2><p>The report still lists attempted searches below.</p><strong></strong><em></em></article>'}
        </section>
        <section class="guide">
          <strong>How to read this:</strong> <code>A &lt;-&gt; B</code> means round trip, and <code>A -&gt; B -&gt; C</code> means different return airport. Cash rows are true two-leg fares; <code>2x cash</code> rows add two one-way fares for comparison. Point value sliders change award effective USD. Score is lower-is-better and includes price plus timing, duration, and stop penalties.
        </section>
        <section class="quality" aria-label="Data quality">
          {escape(quality_summary)}
        </section>
        {f'<section class="errors"><strong>Partial results:</strong> {escape(error_summary)}<details><summary>Show provider details</summary><ul>{error_tags}</ul></details></section>' if errors else ''}
      </section>
    </section>
    <section id="plansView" class="view-panel" hidden>
      <section aria-label="Interactive trip explorer">
        <section class="results-board">
          <div class="result-toolbar">
            <div>
              <h2>Recommended Plans</h2>
              <p><span id="visiblePlanCount">0</span> of {len(complete_rows)} complete plans visible</p>
            </div>
            <label>Sort<select id="sortMode"><option value="score">Adjusted score</option><option value="effective">Effective USD</option><option value="duration">Duration</option><option value="stops">Stops</option></select></label>
          </div>
          <div id="compareTray" class="compare-tray"><strong>Compare</strong><div id="compareList" class="compare-list"></div></div>
          <div id="planResults" class="trip-results">
            {flight_cards}
          </div>
        </section>
      </section>
    </section>
    <section id="buildView" class="view-panel" hidden>
      <section class="builder" aria-label="Build trip">
        <div class="builder-header">
          <div>
            <h2>Build Trip</h2>
            <p>Select an outbound first, then choose a return from matching complete plans.</p>
          </div>
          <label>Plan Type<select id="buildKindFilter"><option value="">All</option><option value="cash">Cash</option><option value="cash + award">Cash + award</option><option value="cash one-ways">Two cash one-ways</option><option value="award pair">Award pair</option></select></label>
        </div>
        <div class="builder-grid">
          <section class="builder-column">
            <h3>1. Outbound <span id="outboundChoiceCount"></span></h3>
            <div id="outboundChoices" class="choice-list"></div>
          </section>
          <section class="builder-column">
            <h3>2. Return <span id="returnChoiceCount"></span></h3>
            <div id="returnChoices" class="choice-list"></div>
          </section>
          <section class="builder-column">
            <h3>Matching Plans <span id="buildResultCount"></span></h3>
            <div id="builderResults" class="builder-results"></div>
          </section>
        </div>
      </section>
    </section>
    <section id="dataView" class="view-panel" hidden>
      {html_table('Complete Plans', complete_tags)}
      {html_table('One-Way Cash Options', cash_one_way_tags)}
      {html_table('Outbound Award Options', outbound_tags)}
      {html_table('Return Award Options', return_tags)}
    </section>
  </main>
  <script>
    const scoreConfig = JSON.parse(document.querySelector("#score-config").textContent).scoreDefaults;
    const controls = {{
      search: document.querySelector("#search"),
      kind: document.querySelector("#kindFilter"),
      trip: document.querySelector("#tripFilter"),
      origin: document.querySelector("#originFilter"),
      destination: document.querySelector("#destinationFilter"),
      outboundDate: document.querySelector("#outboundDateFilter"),
      returnDate: document.querySelector("#returnDateFilter"),
      score: document.querySelector("#scoreFilter"),
      effective: document.querySelector("#effectiveFilter"),
      stops: document.querySelector("#stopsFilter"),
      late: document.querySelector("#lateFilter")
    }};
    const scoreControls = {{
      stop: document.querySelector("#stopPenalty"),
      stopOut: document.querySelector("#stopPenaltyValue"),
      duration: document.querySelector("#durationPenalty"),
      durationOut: document.querySelector("#durationPenaltyValue")
    }};
    const cppControls = Array.from(document.querySelectorAll("[data-cpp-control]"));
    const timePenaltyPlot = document.querySelector("#timePenaltyPlot");
    const timeHourSelect = document.querySelector("#timeHourSelect");
    const timeHourPenalty = document.querySelector("#timeHourPenalty");
    const timeHourPenaltyValue = document.querySelector("#timeHourPenaltyValue");
    const timePenaltySelectedValue = document.querySelector("#timePenaltySelectedValue");
    const sortMode = document.querySelector("#sortMode");
    const buildKindFilter = document.querySelector("#buildKindFilter");
    const visiblePlanCount = document.querySelector("#visiblePlanCount");
    const planResults = document.querySelector("#planResults");
    const compareTray = document.querySelector("#compareTray");
    const compareList = document.querySelector("#compareList");
    const outboundChoices = document.querySelector("#outboundChoices");
    const returnChoices = document.querySelector("#returnChoices");
    const builderResults = document.querySelector("#builderResults");
    const outboundChoiceCount = document.querySelector("#outboundChoiceCount");
    const returnChoiceCount = document.querySelector("#returnChoiceCount");
    const buildResultCount = document.querySelector("#buildResultCount");
    const tables = Array.from(document.querySelectorAll("table"));
    const rows = Array.from(document.querySelectorAll("tbody tr"));
    const cards = Array.from(document.querySelectorAll(".trip-card"));
    const recommendations = Array.from(document.querySelectorAll(".recommendation[data-section='summary']"));
    const scoreItems = [...rows, ...cards, ...recommendations];
    const filterItems = [...rows, ...cards];
    let selectedOutboundKey = "";
    let selectedReturnKey = "";
    let selectedTimeHour = 0;
    let hourlyPenalties = [...(scoreConfig.timePenaltyDefaults || Array(24).fill(0))];
    let draggingTimePlot = false;

    function itemText(item) {{
      return item.innerText.toLowerCase();
    }}
    function valueOf(item, key) {{
      const value = Number(item.dataset[key] || 0);
      return Number.isFinite(value) ? value : 0;
    }}
    function moneyValue(value) {{
      return "$" + value.toLocaleString(undefined, {{ maximumFractionDigits: 0 }});
    }}
    function moneyExact(value) {{
      return "$" + value.toLocaleString(undefined, {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    }}
    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, char => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\\"": "&quot;",
        "'": "&#39;"
      }}[char]));
    }}
    function labelParts(value) {{
      const lines = String(value || "").split("\\n").map(line => line.trim()).filter(Boolean);
      return {{
        title: lines.slice(0, 2).join(" · ") || "Timing unavailable",
        detail: lines.slice(2).join(" · ")
      }};
    }}
    function compactCardText(card) {{
      return {{
        route: card.querySelector(".card-route h2")?.textContent || "Plan",
        date: card.querySelector(".card-route p")?.textContent || "",
        price: card.querySelector(".card-price strong")?.textContent || "",
        effective: card.querySelector(".card-price span")?.textContent || ""
      }};
    }}
    function rangeNumber(input) {{
      return Number(input.value || 0);
    }}
    function dataJson(item, key, fallback) {{
      try {{
        return JSON.parse(item.dataset[key] || "");
      }} catch {{
        return fallback;
      }}
    }}
    function cppValue(program, fallback) {{
      const control = document.querySelector(`[data-cpp-control][data-program="${{program}}"]`);
      return control ? rangeNumber(control) : Number(fallback || 0);
    }}
    function effectiveForItem(item) {{
      const cashComponent = valueOf(item, "cashComponent");
      const components = dataJson(item, "awardComponents", []);
      return components.reduce((total, component) => {{
        const points = Number(component.points || 0);
        const cpp = cppValue(component.key || "", component.cpp);
        return total + points * cpp / 100;
      }}, cashComponent);
    }}
    function timePenaltyForItem(item) {{
      const counts = dataJson(item, "timeHours", []);
      return hourlyPenalties.reduce((total, penalty, hour) => total + Number(penalty || 0) * Number(counts[hour] || 0), 0);
    }}
    function scoreParts(item) {{
      const effective = effectiveForItem(item);
      const stopBase = valueOf(item, "stopPenalty");
      const durationBase = valueOf(item, "durationPenalty");
      const stopPenalty = scoreConfig.stopPenalty ? stopBase * rangeNumber(scoreControls.stop) / scoreConfig.stopPenalty : stopBase;
      const durationPenalty = scoreConfig.durationPenalty ? durationBase * rangeNumber(scoreControls.duration) / scoreConfig.durationPenalty : durationBase;
      const timePenalty = timePenaltyForItem(item);
      const score = effective + stopPenalty + durationPenalty + timePenalty;
      return {{
        effective,
        score,
        parts: [
          "Effective " + moneyExact(effective),
          "Stops +" + moneyValue(stopPenalty),
          "Duration +" + moneyValue(durationPenalty),
          "Bad times +" + moneyValue(timePenalty)
        ]
      }};
    }}
    function updateScores() {{
      scoreItems.forEach(item => {{
        const result = scoreParts(item);
        const score = Number.isFinite(result.score) ? result.score : valueOf(item, "originalScore");
        const effective = Number.isFinite(result.effective) ? result.effective : valueOf(item, "effective");
        item.dataset.effective = effective.toFixed(2);
        item.dataset.score = score.toFixed(2);
        item.dataset.adjustedScore = score.toFixed(2);
        item.querySelectorAll("[data-live-effective]").forEach(target => {{
          target.textContent = moneyExact(effective);
          if (target.dataset.sort !== undefined) target.dataset.sort = effective.toFixed(2);
        }});
        item.querySelectorAll("[data-live-score]").forEach(target => {{
          target.textContent = score.toFixed(2);
          if (target.dataset.sort !== undefined) target.dataset.sort = score.toFixed(2);
        }});
        item.querySelectorAll("[data-breakdown]").forEach(target => {{
          target.innerHTML = result.parts.map(part => `<span>${{part}}</span>`).join("");
        }});
      }});
    }}
    function syncScoreOutputs() {{
      scoreControls.stopOut.textContent = moneyValue(rangeNumber(scoreControls.stop));
      scoreControls.durationOut.textContent = moneyValue(rangeNumber(scoreControls.duration));
      syncTimeEditor();
    }}
    function renderTimePlot() {{
      const maxPenalty = Math.max(100, ...hourlyPenalties);
      timePenaltyPlot.innerHTML = hourlyPenalties.map((penalty, hour) => {{
        const height = Math.max(4, Math.round(Number(penalty || 0) / maxPenalty * 100));
        const active = hour === selectedTimeHour ? " active" : "";
        const label = `${{String(hour).padStart(2, "0")}}:00 ${{moneyValue(Number(penalty || 0))}} per departure/arrival`;
        return `<button type="button" class="hour-bar${{active}}" data-hour="${{hour}}" title="${{escapeHtml(label)}}" aria-label="${{escapeHtml(label)}}" aria-pressed="${{hour === selectedTimeHour}}"><span style="--bar-height:${{height}}%"></span></button>`;
      }}).join("");
    }}
    function syncTimeEditor() {{
      const value = Number(hourlyPenalties[selectedTimeHour] || 0);
      timeHourSelect.value = String(selectedTimeHour);
      timeHourPenalty.value = String(value);
      timeHourPenaltyValue.textContent = moneyValue(value);
      timePenaltySelectedValue.textContent = `${{String(selectedTimeHour).padStart(2, "0")}}:00 · ${{moneyValue(value)}} per event`;
      renderTimePlot();
    }}
    function clamp(value, min, max) {{
      return Math.min(max, Math.max(min, value));
    }}
    function timeEditFromPointer(event) {{
      const rect = timePenaltyPlot.getBoundingClientRect();
      const x = clamp(event.clientX - rect.left, 0, Math.max(1, rect.width - 1));
      const y = clamp(event.clientY - rect.top, 0, rect.height);
      const hour = clamp(Math.floor(x / Math.max(1, rect.width) * 24), 0, 23);
      const rawPenalty = (1 - y / Math.max(1, rect.height)) * Number(timeHourPenalty.max || 200);
      const step = Number(timeHourPenalty.step || 5);
      const penalty = clamp(Math.round(rawPenalty / step) * step, Number(timeHourPenalty.min || 0), Number(timeHourPenalty.max || 200));
      return {{ hour, penalty }};
    }}
    function applyTimePointer(event) {{
      const edit = timeEditFromPointer(event);
      selectedTimeHour = edit.hour;
      hourlyPenalties[selectedTimeHour] = edit.penalty;
      refreshScoresAndViews();
    }}
    function refreshScoresAndViews() {{
      syncScoreOutputs();
      updateScores();
      sortCards();
      applyFilters();
    }}
    function numberLimit(control) {{
      if (control.value === "") return Infinity;
      const value = Number(control.value);
      return Number.isFinite(value) ? value : Infinity;
    }}
    function matchesGlobalFilters(row) {{
      const query = controls.search.value.trim().toLowerCase();
      const maxScore = numberLimit(controls.score);
      const maxEffective = numberLimit(controls.effective);
      const maxStops = numberLimit(controls.stops);
      return (
        (!query || itemText(row).includes(query)) &&
        (!controls.kind.value || row.dataset.kind === controls.kind.value) &&
        (!controls.trip.value || row.dataset.tripType === controls.trip.value) &&
        (!controls.origin.value || row.dataset.origin === controls.origin.value) &&
        (!controls.destination.value || row.dataset.destination === controls.destination.value) &&
        (!controls.outboundDate.value || row.dataset.outboundDate === controls.outboundDate.value) &&
        (!controls.returnDate.value || row.dataset.returnDate === controls.returnDate.value) &&
        (Number(row.dataset.score) <= maxScore) &&
        (Number(row.dataset.effective) <= maxEffective) &&
        (Number(row.dataset.stops) <= maxStops) &&
        (!controls.late.value || row.dataset.late === controls.late.value)
      );
    }}
    function applyFilters() {{
      let visibleCards = 0;
      filterItems.forEach(row => {{
        const keep = matchesGlobalFilters(row);
        row.hidden = !keep;
        if (keep && row.classList.contains("trip-card")) visibleCards += 1;
      }});
      visiblePlanCount.textContent = visibleCards;
      syncQuickTabs();
      renderBuilder();
      updateCompareTray();
    }}
    function sortValue(row, index) {{
      const cell = row.children[index];
      const raw = cell.dataset.sort ?? cell.innerText;
      const numeric = Number(raw);
      return Number.isNaN(numeric) ? raw.toLowerCase() : numeric;
    }}
    function sortCards() {{
      const mode = sortMode.value;
      const sorted = [...cards].sort((a, b) => {{
        const av = Number(a.dataset[mode === "score" ? "adjustedScore" : mode] || 0);
        const bv = Number(b.dataset[mode === "score" ? "adjustedScore" : mode] || 0);
        return av - bv;
      }});
      sorted.forEach(card => planResults.appendChild(card));
    }}
    function syncQuickTabs() {{
      document.querySelectorAll("[data-kind-preset]").forEach(button => {{
        button.classList.toggle("active", button.dataset.kindPreset === controls.kind.value);
      }});
    }}
    function updateCompareTray() {{
      const selected = cards.filter(card => card.querySelector("[data-compare-plan]")?.checked && !card.hidden);
      cards.forEach(card => card.classList.toggle("selected", card.querySelector("[data-compare-plan]")?.checked));
      compareTray.classList.toggle("active", selected.length > 0);
      if (!selected.length) {{
        compareList.innerHTML = "";
        return;
      }}
      const baselineScore = Number(selected[0].dataset.adjustedScore || 0);
      const baselineEffective = Number(selected[0].dataset.effective || 0);
      compareList.innerHTML = selected.slice(0, 4).map((card, index) => {{
        const text = compactCardText(card);
        const score = Number(card.dataset.adjustedScore || 0);
        const effective = Number(card.dataset.effective || 0);
        const scoreDelta = index === 0 ? "Baseline" : `${{score >= baselineScore ? "+" : ""}}${{(score - baselineScore).toFixed(2)}} score`;
        const effectiveDelta = index === 0 ? "Effective baseline" : `${{effective >= baselineEffective ? "+" : "-"}}${{moneyValue(Math.abs(effective - baselineEffective))}} effective`;
        const note = card.querySelector(".card-note")?.textContent || card.querySelector(".card-details p")?.textContent || "";
        return (
          '<article class="compare-item">' +
          `<h3>${{escapeHtml(text.route)}}</h3>` +
          `<p>${{escapeHtml(text.date)}}</p>` +
          '<div class="compare-meta">' +
          `<span>${{escapeHtml(card.dataset.kind || "")}}</span>` +
          `<span>${{escapeHtml(text.price || text.effective)}}</span>` +
          `<span>score ${{escapeHtml(score.toFixed(2))}}</span>` +
          `<span>${{escapeHtml(scoreDelta)}}</span>` +
          `<span>${{escapeHtml(effectiveDelta)}}</span>` +
          '</div>' +
          compareLegHtml("Outbound", card.dataset.outboundLabel) +
          compareLegHtml("Return", card.dataset.returnLabel) +
          (note ? `<p>${{escapeHtml(note)}}</p>` : '') +
          '</article>'
        );
      }}).join("") + (selected.length > 4 ? `<article class="compare-item"><h3>${{selected.length - 4}} more selected</h3><p>Showing the first four visible plans to keep the comparison readable.</p></article>` : "");
    }}
    function compareLegHtml(label, value) {{
      const lines = String(value || "").split("\\n").map(line => line.trim()).filter(Boolean);
      const rendered = lines.length ? lines.map(line => `<span>${{escapeHtml(line)}}</span>`).join("") : '<span>Timing unavailable</span>';
      return `<div class="compare-leg"><strong>${{escapeHtml(label)}}</strong>${{rendered}}</div>`;
    }}
    function builderPool() {{
      return cards.filter(card => matchesGlobalFilters(card) && (!buildKindFilter.value || card.dataset.kind === buildKindFilter.value));
    }}
    function bestByKey(items, keyName) {{
      const groups = new Map();
      items.forEach(card => {{
        const key = card.dataset[keyName] || "";
        if (!key) return;
        const current = groups.get(key);
        if (!current || Number(card.dataset.adjustedScore) < Number(current.dataset.adjustedScore)) {{
          groups.set(key, card);
        }}
      }});
      return [...groups.entries()].sort((a, b) => Number(a[1].dataset.adjustedScore) - Number(b[1].dataset.adjustedScore));
    }}
    function choiceButton(key, sampleCard, keyName, selectedKey) {{
      const labelName = keyName === "outboundKey" ? "outboundLabel" : "returnLabel";
      const parts = labelParts(sampleCard.dataset[labelName]);
      const count = builderPool().filter(card => card.dataset[keyName] === key).length;
      return (
        `<button type="button" class="leg-choice ${{key === selectedKey ? "active" : ""}}" data-choice-key="${{escapeHtml(key)}}">` +
        `<strong>${{escapeHtml(parts.title)}}</strong>` +
        `<span>${{escapeHtml(parts.detail || "Best score " + sampleCard.dataset.adjustedScore)}}</span>` +
        `<span>${{count}} plan${{count === 1 ? "" : "s"}} · best score ${{escapeHtml(sampleCard.dataset.adjustedScore || "")}}</span>` +
        `</button>`
      );
    }}
    function renderBuilder() {{
      const pool = builderPool();
      const outboundGroups = bestByKey(pool, "outboundKey");
      if (selectedOutboundKey && !outboundGroups.some(([key]) => key === selectedOutboundKey)) {{
        selectedOutboundKey = "";
        selectedReturnKey = "";
      }}
      if (!selectedOutboundKey && outboundGroups.length) selectedOutboundKey = outboundGroups[0][0];
      outboundChoiceCount.textContent = outboundGroups.length ? `(${{outboundGroups.length}})` : "";
      outboundChoices.innerHTML = outboundGroups.length
        ? outboundGroups.map(([key, card]) => choiceButton(key, card, "outboundKey", selectedOutboundKey)).join("")
        : '<div class="empty-results">No outbound choices match this plan type.</div>';

      const returnPool = selectedOutboundKey ? pool.filter(card => card.dataset.outboundKey === selectedOutboundKey) : [];
      const returnGroups = bestByKey(returnPool, "returnKey");
      if (selectedReturnKey && !returnGroups.some(([key]) => key === selectedReturnKey)) selectedReturnKey = "";
      if (!selectedReturnKey && returnGroups.length) selectedReturnKey = returnGroups[0][0];
      returnChoiceCount.textContent = returnGroups.length ? `(${{returnGroups.length}})` : "";
      returnChoices.innerHTML = selectedOutboundKey
        ? (returnGroups.length ? returnGroups.map(([key, card]) => choiceButton(key, card, "returnKey", selectedReturnKey)).join("") : '<div class="empty-results">No return choices match this outbound.</div>')
        : '<div class="empty-results">Choose an outbound first.</div>';

      const matches = pool
        .filter(card => (!selectedOutboundKey || card.dataset.outboundKey === selectedOutboundKey) && (!selectedReturnKey || card.dataset.returnKey === selectedReturnKey))
        .sort((a, b) => Number(a.dataset.adjustedScore) - Number(b.dataset.adjustedScore));
      buildResultCount.textContent = matches.length ? `(${{matches.length}})` : "";
      builderResults.innerHTML = matches.length
        ? matches.slice(0, 30).map(card => {{
            const text = compactCardText(card);
            const note = card.querySelector(".card-note")?.textContent || "";
            return (
              '<article class="builder-card">' +
              `<h3>${{escapeHtml(text.route)}}</h3>` +
              `<p>${{escapeHtml(text.date)}}</p>` +
              '<div class="builder-meta">' +
              `<span>${{escapeHtml(card.dataset.kind || "")}}</span>` +
              `<span>${{escapeHtml(text.price)}}</span>` +
              `<span>${{escapeHtml(text.effective)}}</span>` +
              `<span>score ${{escapeHtml(card.dataset.adjustedScore || "")}}</span>` +
              '</div>' +
              (note ? `<p>${{escapeHtml(note)}}</p>` : '') +
              '</article>'
            );
          }}).join("")
        : '<div class="empty-results">No complete plans match this outbound and return pair.</div>';
    }}
    function showView(name) {{
      document.querySelectorAll("[data-view-tab]").forEach(button => {{
        button.classList.toggle("active", button.dataset.viewTab === name);
      }});
      document.querySelectorAll(".view-panel").forEach(panel => {{
        panel.hidden = panel.id !== `${{name}}View`;
      }});
      if (name === "build") renderBuilder();
    }}
    tables.forEach(table => {{
      const body = table.querySelector("tbody");
      table.querySelectorAll("th").forEach((th, index) => {{
        let direction = "asc";
        th.addEventListener("click", () => {{
          const tableRows = Array.from(body.querySelectorAll("tr"));
          direction = direction === "asc" ? "desc" : "asc";
          tableRows.sort((a, b) => {{
            const av = sortValue(a, index);
            const bv = sortValue(b, index);
            if (av < bv) return direction === "asc" ? -1 : 1;
            if (av > bv) return direction === "asc" ? 1 : -1;
            return 0;
          }});
          tableRows.forEach(row => body.appendChild(row));
          applyFilters();
        }});
      }});
    }});
    Object.values(controls).forEach(control => {{
      control.addEventListener("input", applyFilters);
      control.addEventListener("change", applyFilters);
    }});
    Object.values(scoreControls).filter(control => control instanceof HTMLInputElement).forEach(control => {{
      control.addEventListener("input", refreshScoresAndViews);
    }});
    cppControls.forEach(control => {{
      control.addEventListener("input", refreshScoresAndViews);
      control.addEventListener("change", refreshScoresAndViews);
    }});
    timeHourSelect.addEventListener("change", () => {{
      selectedTimeHour = Number(timeHourSelect.value || 0);
      syncTimeEditor();
    }});
    timeHourPenalty.addEventListener("input", () => {{
      hourlyPenalties[selectedTimeHour] = rangeNumber(timeHourPenalty);
      refreshScoresAndViews();
    }});
    timePenaltyPlot.addEventListener("pointerdown", event => {{
      draggingTimePlot = true;
      timePenaltyPlot.setPointerCapture(event.pointerId);
      event.preventDefault();
      applyTimePointer(event);
    }});
    timePenaltyPlot.addEventListener("pointermove", event => {{
      if (!draggingTimePlot) return;
      event.preventDefault();
      applyTimePointer(event);
    }});
    timePenaltyPlot.addEventListener("pointerup", event => {{
      draggingTimePlot = false;
      if (timePenaltyPlot.hasPointerCapture(event.pointerId)) {{
        timePenaltyPlot.releasePointerCapture(event.pointerId);
      }}
    }});
    timePenaltyPlot.addEventListener("pointercancel", event => {{
      draggingTimePlot = false;
      if (timePenaltyPlot.hasPointerCapture(event.pointerId)) {{
        timePenaltyPlot.releasePointerCapture(event.pointerId);
      }}
    }});
    sortMode.addEventListener("change", () => {{
      sortCards();
      applyFilters();
    }});
    buildKindFilter.addEventListener("change", () => {{
      selectedOutboundKey = "";
      selectedReturnKey = "";
      renderBuilder();
    }});
    document.querySelectorAll("[data-kind-preset]").forEach(button => {{
      button.addEventListener("click", () => {{
        controls.kind.value = button.dataset.kindPreset;
        applyFilters();
      }});
    }});
    document.querySelectorAll("[data-view-tab]").forEach(button => {{
      button.addEventListener("click", () => showView(button.dataset.viewTab));
    }});
    outboundChoices.addEventListener("click", event => {{
      const button = event.target.closest("[data-choice-key]");
      if (!button) return;
      selectedOutboundKey = button.dataset.choiceKey;
      selectedReturnKey = "";
      renderBuilder();
    }});
    returnChoices.addEventListener("click", event => {{
      const button = event.target.closest("[data-choice-key]");
      if (!button) return;
      selectedReturnKey = button.dataset.choiceKey;
      renderBuilder();
    }});
    document.addEventListener("click", event => {{
      const detailButton = event.target.closest("[data-toggle-details]");
      if (!detailButton) return;
      const card = detailButton.closest(".trip-card");
      const details = card.querySelector(".card-details");
      details.hidden = !details.hidden;
      detailButton.textContent = details.hidden ? "Details" : "Hide details";
    }});
    document.addEventListener("change", event => {{
      if (event.target.matches("[data-compare-plan]")) updateCompareTray();
    }});
    refreshScoresAndViews();
    renderBuilder();
  </script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def html_table(title: str, row_tags: str) -> str:
    return f"""
    <section class="panel">
      <h2>{escape(title)}</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th title="Click to sort">Kind</th>
              <th title="Click to sort">Plan</th>
              <th title="Click to sort">Outbound</th>
              <th title="Click to sort">Return</th>
              <th title="Click to sort">Price</th>
              <th title="Click to sort">Effective USD</th>
              <th title="Click to sort">Score</th>
              <th title="Click to sort">Stops</th>
              <th title="Click to sort">Duration</th>
              <th title="Click to sort">Notes</th>
            </tr>
          </thead>
          <tbody>{row_tags}</tbody>
        </table>
      </div>
    </section>
    """


def collect_errors(award_runs: list[dict[str, Any]], cash_runs: list[dict[str, Any]]) -> list[str]:
    errors = []
    for run in award_runs:
        if run.get("error"):
            leg = run["leg"]
            errors.append(f"Award {leg['direction']} {leg['origin']} -> {leg['destination']} {leg['date']}: {compact_error(run['error'])}")
    for run in cash_runs:
        if run.get("error"):
            if "itinerary" in run:
                itinerary = run["itinerary"]
                errors.append(f"Cash {itinerary['route']} {itinerary['dates']}: {compact_error(run['error'])}")
            else:
                leg = run["cash_leg"]
                errors.append(f"Cash one-way {leg['direction']} {leg['origin']} -> {leg['destination']} {leg['date']}: {compact_error(run['error'])}")
        elif run.get("summary", {}).get("provider_error"):
            if "itinerary" in run:
                itinerary = run["itinerary"]
                errors.append(f"Cash {itinerary['route']} {itinerary['dates']}: {compact_error(run['summary']['provider_error'])}")
            else:
                leg = run["cash_leg"]
                errors.append(
                    f"Cash one-way {leg['direction']} {leg['origin']} -> {leg['destination']} {leg['date']}: "
                    f"{compact_error(run['summary']['provider_error'])}"
                )
    return errors


def run_trip_search(
    *,
    origins: list[str],
    destinations: list[str],
    outbound_dates: list[str],
    return_dates: list[str],
    cabin: str,
    adults: int,
    currency: str,
    fetch_mode: str,
    max_stops: int | None,
    base_url: str,
    preferences_path: Path,
    refresh: bool,
    offline_fx: bool,
    output_dir: Path,
    skip_awards: bool,
    skip_cash: bool,
    award_per_leg_limit: int,
    award_pair_limit: int,
    cash_one_way_per_leg_limit: int,
    cash_one_way_pair_limit: int,
    mixed_plan_limit: int,
    best_limit: int | None,
    award_workers: int = 2,
    cash_workers: int = 3,
) -> dict[str, Any]:
    plan = expand_trip_search(
        origins=origins,
        destinations=destinations,
        outbound_dates=outbound_dates,
        return_dates=return_dates,
    )

    award_runs = []
    if not skip_awards:
        award_legs = [*plan.outbound_legs, *plan.return_legs]
        award_runs = run_ordered_workers(
            award_legs,
            workers=award_workers,
            runner=lambda leg: run_award_leg(
                leg,
                base_url=base_url,
                output_dir=WORKSPACE_ROOT / "seat_aero" / "data",
                preferences_path=preferences_path,
                refresh=refresh,
                offline_fx=offline_fx,
                best_limit=best_limit,
            ),
        )

    cash_runs = []
    cash_one_way_runs = []
    if not skip_cash:
        cash_one_way_runs = run_ordered_workers(
            plan.cash_one_way_legs,
            workers=cash_workers,
            runner=lambda leg: run_cash_one_way_leg(
                leg,
                cabin=cabin,
                adults=adults,
                currency=currency,
                fetch_mode=fetch_mode,
                max_stops=max_stops,
                output_dir=WORKSPACE_ROOT / "cash" / "data",
                preferences_path=preferences_path,
                refresh=refresh,
            ),
        )
        cash_runs = run_ordered_workers(
            plan.cash_itineraries,
            workers=cash_workers,
            runner=lambda itinerary: run_cash_itinerary(
                itinerary,
                cabin=cabin,
                adults=adults,
                currency=currency,
                fetch_mode=fetch_mode,
                max_stops=max_stops,
                output_dir=WORKSPACE_ROOT / "cash" / "data",
                preferences_path=preferences_path,
                refresh=refresh,
            ),
        )

    award_rows = award_leg_rows(award_runs, cabin=cabin, per_leg_limit=award_per_leg_limit)
    cash_one_way_rows = cash_one_way_leg_rows(cash_one_way_runs, per_leg_limit=cash_one_way_per_leg_limit)
    cash_plan_rows = top_cash_plan_rows(cash_runs)
    cash_one_way_plan_rows = cash_one_way_pair_rows(cash_one_way_rows, limit=cash_one_way_pair_limit)
    cash_plan_rows, cash_one_way_plan_rows = annotate_cash_strategy_comparisons(
        cash_plan_rows,
        cash_one_way_plan_rows,
    )
    complete_rows = [
        *cash_plan_rows,
        *cash_one_way_plan_rows,
        *mixed_cash_award_rows(cash_one_way_rows, award_rows, limit=mixed_plan_limit),
        *award_pair_rows(award_rows, limit=award_pair_limit),
    ]
    complete_rows = sorted(
        deduplicate_rows(complete_rows),
        key=lambda row: (row["score"], row["effective_num"], row["stops_num"]),
    )

    stem = search_stem(origins, destinations, outbound_dates, return_dates, cabin)
    title = f"{'/'.join(origins)} to {'/'.join(destinations)} Trip Search"
    json_path = output_dir / f"{stem}_trip_summary.json"
    html_path = output_dir / f"{stem}_trip_summary.html"
    errors = collect_errors(award_runs, [*cash_runs, *cash_one_way_runs])
    write_master_json(
        json_path,
        plan=plan,
        award_runs=award_runs,
        cash_runs=cash_runs,
        cash_one_way_runs=cash_one_way_runs,
        complete_rows=complete_rows,
        award_rows=award_rows,
        cash_one_way_rows=cash_one_way_rows,
    )
    write_master_html(
        html_path,
        title=title,
        cabin=cabin,
        plan=plan,
        complete_rows=complete_rows,
        award_rows=award_rows,
        cash_one_way_rows=cash_one_way_rows,
        errors=errors,
        preferences_path=preferences_path,
        data_mode="live refresh requested" if refresh else "cached allowed",
    )
    return {
        "counts": {
            "outbound_award_legs": len(plan.outbound_legs),
            "return_award_legs": len(plan.return_legs),
            "cash_one_way_legs": len(plan.cash_one_way_legs),
            "cash_itineraries": len(plan.cash_itineraries),
            "cash_one_way_rows": len(cash_one_way_rows),
            "cash_one_way_plan_rows": len([row for row in complete_rows if row["kind"] == "cash one-ways"]),
            "mixed_plan_rows": len([row for row in complete_rows if row["kind"] == "cash + award"]),
            "complete_plan_rows": len(complete_rows),
            "award_leg_rows": len(award_rows),
            "errors": len(errors),
            "award_workers": max(0, award_workers),
            "cash_workers": max(0, cash_workers),
        },
        "outputs": {
            "json": str(json_path),
            "html": str(html_path),
        },
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a multi-airport, multi-date trip search and build a master report.")
    parser.add_argument("--origins", required=True, help="Comma-delimited origin airports, e.g. SFO,SJC.")
    parser.add_argument("--destinations", required=True, help="Comma-delimited destination airports, e.g. FCA,MSO.")
    parser.add_argument("--outbound-dates", required=True, help="Comma-delimited outbound dates in YYYY-MM-DD format.")
    parser.add_argument("--return-dates", required=True, help="Comma-delimited return dates in YYYY-MM-DD format.")
    parser.add_argument("--cabin", default="economy", choices=["economy", "premium-economy", "business", "first"])
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--fetch-mode", default="fallback", choices=["common", "fallback", "force-fallback", "local"])
    parser.add_argument("--max-stops", type=int, default=None)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--preferences", default=str(DEFAULT_PREFERENCES_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--refresh", action="store_true", help="Refresh cash and award provider data.")
    parser.add_argument("--offline-fx", action="store_true", help="Use cached FX snapshots for award tax conversion.")
    parser.add_argument("--skip-awards", action="store_true")
    parser.add_argument("--skip-cash", action="store_true")
    parser.add_argument("--award-per-leg-limit", type=int, default=3)
    parser.add_argument("--award-pair-limit", type=int, default=80)
    parser.add_argument("--cash-one-way-per-leg-limit", type=int, default=2)
    parser.add_argument("--cash-one-way-pair-limit", type=int, default=80)
    parser.add_argument("--mixed-plan-limit", type=int, default=80)
    parser.add_argument("--best-limit", type=int, default=None)
    parser.add_argument("--award-workers", type=int, default=2, help="Concurrent award leg searches. Use 1 for serial.")
    parser.add_argument("--cash-workers", type=int, default=3, help="Concurrent paid itinerary searches. Use 1 for serial.")
    args = parser.parse_args()

    summary = run_trip_search(
        origins=csv_values(args.origins, uppercase=True),
        destinations=csv_values(args.destinations, uppercase=True),
        outbound_dates=csv_values(args.outbound_dates),
        return_dates=csv_values(args.return_dates),
        cabin=args.cabin,
        adults=args.adults,
        currency=args.currency,
        fetch_mode=args.fetch_mode,
        max_stops=args.max_stops,
        base_url=args.base_url,
        preferences_path=Path(args.preferences),
        refresh=args.refresh,
        offline_fx=args.offline_fx,
        output_dir=Path(args.output_dir),
        skip_awards=args.skip_awards,
        skip_cash=args.skip_cash,
        award_per_leg_limit=args.award_per_leg_limit,
        award_pair_limit=args.award_pair_limit,
        cash_one_way_per_leg_limit=args.cash_one_way_per_leg_limit,
        cash_one_way_pair_limit=args.cash_one_way_pair_limit,
        mixed_plan_limit=args.mixed_plan_limit,
        best_limit=args.best_limit,
        award_workers=args.award_workers,
        cash_workers=args.cash_workers,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
