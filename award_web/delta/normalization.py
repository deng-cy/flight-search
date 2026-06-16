from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from flight_search_common.scoring import score_cash_itinerary

from ..models import AwardWebSearchRequest


SFAF_ERROR_RE = re.compile(r"#SFAF\d+", re.IGNORECASE)
POINTS_RE = re.compile(r"(?<![\w$])(?P<points>\d[\d,]*)\s*(?:miles?|mi)\b", re.IGNORECASE)
MONEY_RE = re.compile(r"\$\s*(?P<amount>\d[\d,]*(?:\.\d{2})?)")
NUMBER_LINE_RE = re.compile(r"^\d[\d,]*(?:\.\d{1,2})?$")
FLIGHT_RE = re.compile(r"\bDL\s*\d{2,4}\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>[AP]M)\b", re.IGNORECASE)
DURATION_RE = re.compile(r"\b(?:(?P<hours>\d+)\s*h(?:r|rs)?\.?\s*)?(?:(?P<minutes>\d+)\s*m(?:in)?\.?)?\b", re.IGNORECASE)
STOP_RE = re.compile(r"\b(?P<stops>\d+)\s+stops?\b", re.IGNORECASE)


def compact_text(value: Any) -> str:
    return re.sub(r"[ \t]+", " ", str(value or "")).strip()


def page_status(text: str) -> tuple[str, str]:
    body = compact_text(text)
    if "Access Denied" in body and "permission to access this server" in body:
        return "access_denied", body[:240]
    error_match = SFAF_ERROR_RE.search(body)
    if error_match:
        start = max(0, error_match.start() - 120)
        end = min(len(body), error_match.end() + 120)
        return "provider_error", body[start:end]
    lowered = body.lower()
    if "problem processing your request" in lowered:
        return "provider_error", "Delta reported a problem processing the request"
    if "no flights" in lowered or "no results" in lowered:
        return "no_results", "Delta displayed no matching flights"
    if POINTS_RE.search(body):
        return "observed", "Delta displayed mileage text"
    return "unknown", "Delta page did not expose parseable award result text"


def program_cents_per_point(source_name: str, preferences: dict[str, Any]) -> tuple[str, float]:
    programs = preferences.get("points", {}).get("programs", {})
    source = source_name.lower()
    program = programs.get(source, {})
    label = str(program.get("label") or "Delta SkyMiles")
    default_cpp = float(preferences.get("points", {}).get("default_cents_per_point", 2.0))
    return label, float(program.get("cents_per_point", default_cpp))


def parse_usd(text: str) -> float | None:
    match = MONEY_RE.search(text)
    if not match:
        return None
    return float(match.group("amount").replace(",", ""))


def parse_points_from_lines(lines: list[str], index: int) -> int | None:
    line_match = POINTS_RE.search(lines[index])
    if line_match:
        return int(line_match.group("points").replace(",", ""))
    if lines[index].lower() in {"mile", "miles"} and index > 0 and NUMBER_LINE_RE.match(lines[index - 1]):
        return int(lines[index - 1].replace(",", ""))
    return None


def parse_usd_from_lines(lines: list[str], start: int, end: int, fallback_text: str) -> float | None:
    amount = parse_usd(fallback_text)
    if amount is not None:
        return amount
    for index in range(start, end - 1):
        if lines[index] == "$" and NUMBER_LINE_RE.match(lines[index + 1]):
            return float(lines[index + 1].replace(",", ""))
    return None


def normalize_time(text: str) -> str:
    match = TIME_RE.search(text)
    if not match:
        return ""
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = match.group("ampm").upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def parse_duration_minutes(text: str) -> int | str:
    for match in DURATION_RE.finditer(text):
        hours = match.group("hours")
        minutes = match.group("minutes")
        if not hours and not minutes:
            continue
        return int(hours or 0) * 60 + int(minutes or 0)
    return ""


def parse_stops(text: str) -> int | str:
    if re.search(r"\bnonstop\b|\bnon-stop\b", text, re.IGNORECASE):
        return 0
    match = STOP_RE.search(text)
    if match:
        return int(match.group("stops"))
    return ""


def likely_cabin(text: str, fallback: str) -> str:
    lowered = text.lower()
    if "delta one" in lowered or "business" in lowered:
        return "business"
    if "first" in lowered:
        return "first"
    if "premium select" in lowered or "premium economy" in lowered:
        return "premium-economy"
    if "main" in lowered or "basic" in lowered or "comfort" in lowered:
        return "economy"
    return fallback


def fare_brand_flag(text: str) -> str:
    lowered = text.lower()
    if "delta main" in lowered:
        return "fare_brand:delta_main"
    if "delta comfort" in lowered:
        return "fare_brand:delta_comfort"
    if "delta first" in lowered:
        return "fare_brand:delta_first"
    if "delta one" in lowered:
        return "fare_brand:delta_one"
    return ""


def text_windows(lines: list[str], index: int, radius: int = 8) -> str:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return "\n".join(lines[start:end])


def collect_flight_context(lines: list[str], index: int) -> dict[str, Any]:
    flights: list[str] = []
    cursor = index
    while cursor < len(lines):
        line = lines[cursor]
        if line == ",":
            cursor += 1
            continue
        matches = [match.upper().replace(" ", "") for match in FLIGHT_RE.findall(line)]
        if not matches:
            break
        flights.extend(matches)
        cursor += 1

    if not flights:
        return {}

    nearby = "\n".join(lines[max(0, index - 5) : min(len(lines), cursor + 12)])
    duration_minutes = parse_duration_minutes(nearby)
    duration_display = ""
    if isinstance(duration_minutes, int):
        duration_display = f"{duration_minutes // 60}h {duration_minutes % 60}m".strip()
    times = [normalize_time(item.group(0)) for item in TIME_RE.finditer(nearby)]
    times = [item for item in times if item]
    stops = parse_stops(nearby)
    if stops == "" and len(flights) > 1:
        stops = len(flights) - 1

    return {
        "flight_numbers": ", ".join(dict.fromkeys(flights)),
        "depart_time": times[0] if times else "",
        "arrive_time": times[1] if len(times) > 1 else "",
        "duration_minutes": duration_minutes,
        "duration_display": duration_display,
        "stops": stops,
    }


def normalize_delta_payload(
    payload: dict[str, Any],
    request: AwardWebSearchRequest,
    evidence_path: Path,
    preferences: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    preferences = preferences or {}
    text = str(payload.get("body_text") or payload.get("text") or "")
    status = str(payload.get("status") or page_status(text)[0])
    status_message = str(payload.get("status_message") or page_status(text)[1])
    created_at = str(payload.get("created_at") or "")
    _, cpp = program_cents_per_point(request.source_name, preferences)

    lines = [compact_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    current_flight: dict[str, Any] = {}

    for index, line in enumerate(lines):
        if FLIGHT_RE.search(line):
            maybe_flight = collect_flight_context(lines, index)
            if maybe_flight:
                current_flight = maybe_flight

        points = parse_points_from_lines(lines, index)
        if points is None:
            continue
        if not current_flight.get("flight_numbers"):
            continue

        start = max(0, index - 6)
        end = min(len(lines), index + 8 + 1)
        price_window = "\n".join(lines[start:end])
        fare_context = "\n".join(lines[max(0, index - 4) : min(len(lines), index + 4 + 1)])

        taxes = parse_usd_from_lines(lines, start, end, price_window)
        if taxes is None:
            taxes = 5.60 if request.origin and request.destination else 0.0
        effective_usd = round(points * cpp / 100 + taxes, 2)
        flight_numbers = str(current_flight.get("flight_numbers", ""))
        depart_time = str(current_flight.get("depart_time", ""))
        arrive_time = str(current_flight.get("arrive_time", ""))
        stops = current_flight.get("stops", "")
        duration_minutes = current_flight.get("duration_minutes", "")
        duration_display = str(current_flight.get("duration_display", ""))

        scoring = score_cash_itinerary(
            effective_usd=effective_usd,
            stops=stops,
            duration_minutes=duration_minutes,
            depart_time=depart_time,
            arrive_time=arrive_time,
            preferences=preferences,
        )
        flags = ["delta_web_observation"]
        brand_flag = fare_brand_flag(fare_context)
        if brand_flag:
            flags.append(brand_flag)
        flags.extend(scoring["flags"])
        if status != "observed":
            flags.append(f"status:{status}")

        key = (flight_numbers, points, taxes, depart_time, arrive_time, request.trip_type)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "origin": request.origin,
                "destination": request.destination,
                "departure_date": request.departure_date,
                "trip_type": request.trip_type,
                "return_origin": request.return_origin or "",
                "return_destination": request.return_destination or "",
                "return_date": request.return_date or "",
                "depart_time": depart_time,
                "arrive_time": arrive_time,
                "flight_numbers": flight_numbers,
                "carriers": "DL",
                "cabin": likely_cabin(fare_context, request.cabin),
                "stops": stops,
                "source_type": "web_award",
                "source_name": request.source_name,
                "points": points,
                "cash_price_usd": "",
                "taxes_usd": round(taxes, 2),
                "effective_usd": effective_usd,
                "bookable": status == "observed",
                "remaining_seats": "",
                "confidence": "medium" if status == "observed" else "low",
                "evidence_path": str(evidence_path),
                "stop_penalty_usd": scoring["stop_penalty_usd"],
                "duration_penalty_usd": scoring["duration_penalty_usd"],
                "time_penalty_usd": scoring["time_penalty_usd"],
                "next_day_penalty_usd": scoring["next_day_penalty_usd"],
                "seat_credit_usd": 0.0,
                "score": scoring["score"],
                "flags": ", ".join(dict.fromkeys(flags)),
                "duration_minutes": duration_minutes,
                "duration_display": duration_display,
                "raw_price": f"{points:,} miles + ${taxes:g}",
                "raw_text": "\n".join([current_flight.get("flight_numbers", ""), price_window]).strip(),
                "status": status,
                "status_message": status_message,
                "created_at": created_at,
            }
        )

    return rows
