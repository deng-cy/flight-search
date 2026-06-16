from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from flight_search_common.scoring import score_cash_itinerary

from ..models import AwardWebSearchRequest


POINTS_RE = re.compile(r"(?<![\w$])(?P<points>\d[\d,]*)\s*(?:pts?|points?)\b", re.IGNORECASE)
MONEY_RE = re.compile(r"\$\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)")
NUMBER_LINE_RE = re.compile(r"^\d[\d,]*(?:\.\d{1,2})?$")
FLIGHT_RE = re.compile(r"\bWN\s*\d{1,4}\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>[AP]\.?M\.?)\b", re.IGNORECASE)
DURATION_RE = re.compile(r"\b(?:(?P<hours>\d+)\s*h(?:r|rs)?\.?\s*)?(?:(?P<minutes>\d+)\s*m(?:in)?\.?)?\b", re.IGNORECASE)
STOP_RE = re.compile(r"\b(?P<stops>\d+)\s+stops?\b", re.IGNORECASE)


def compact_text(value: Any) -> str:
    return re.sub(r"[ \t]+", " ", str(value or "")).strip()


def page_status(text: str) -> tuple[str, str]:
    body = compact_text(text)
    lowered = body.lower()
    if "access denied" in lowered and "permission" in lowered:
        return "access_denied", body[:240]
    if "unable to complete" in lowered or "try again" in lowered and "southwest" in lowered:
        return "provider_error", body[:240]
    if "no flights available" in lowered or "no flights were found" in lowered:
        return "no_results", "Southwest displayed no matching flights"
    if POINTS_RE.search(body) and FLIGHT_RE.search(body):
        return "observed", "Southwest displayed flight and points text"
    if "book a flight" in lowered and "search flights" in lowered:
        return "search_not_completed", "Southwest stayed on the booking form"
    return "unknown", "Southwest page did not expose parseable award result text"


def program_cents_per_point(source_name: str, preferences: dict[str, Any]) -> tuple[str, float]:
    programs = preferences.get("points", {}).get("programs", {})
    source = source_name.lower()
    program = programs.get(source, {})
    label = str(program.get("label") or "Southwest Rapid Rewards")
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
    if lines[index].lower() in {"pt", "pts", "point", "points"} and index > 0 and NUMBER_LINE_RE.match(lines[index - 1]):
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
    ampm = match.group("ampm").replace(".", "").upper()
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


def duration_display(value: int | str) -> str:
    if not isinstance(value, int):
        return ""
    hours, minutes = divmod(value, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def fare_brand_flag(text: str) -> str:
    lowered = text.lower()
    if "choice extra" in lowered:
        return "fare_brand:choice_extra"
    if "choice preferred" in lowered:
        return "fare_brand:choice_preferred"
    if re.search(r"\bchoice\b", lowered):
        return "fare_brand:choice"
    if re.search(r"\bbasic\b", lowered):
        return "fare_brand:basic"
    if "wanna get away plus" in lowered:
        return "fare_brand:wanna_get_away_plus"
    if "wanna get away" in lowered:
        return "fare_brand:wanna_get_away"
    return ""


def collect_flight_context(lines: list[str], index: int, radius: int = 14) -> dict[str, Any]:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    nearby = "\n".join(lines[start:end])
    flights = [match.upper().replace(" ", "") for match in FLIGHT_RE.findall(nearby)]
    flights = list(dict.fromkeys(flights))
    if not flights:
        return {}

    times = [normalize_time(item.group(0)) for item in TIME_RE.finditer(nearby)]
    times = [item for item in times if item]
    stops = parse_stops(nearby)
    if stops == "" and len(flights) > 1:
        stops = len(flights) - 1
    duration_minutes = parse_duration_minutes(nearby)

    return {
        "flight_numbers": " / ".join(flights),
        "depart_time": times[0] if times else "",
        "arrive_time": times[1] if len(times) > 1 else "",
        "duration_minutes": duration_minutes,
        "duration_display": duration_display(duration_minutes),
        "stops": stops,
        "raw_context": nearby,
    }


def normalize_southwest_payload(
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

    for index, _line in enumerate(lines):
        points = parse_points_from_lines(lines, index)
        if points is None:
            continue

        context = collect_flight_context(lines, index)
        if not context:
            continue

        start = max(0, index - 8)
        end = min(len(lines), index + 8 + 1)
        price_window = "\n".join(lines[start:end])
        taxes = parse_usd_from_lines(lines, start, end, price_window)
        if taxes is None:
            taxes = 5.60

        effective_usd = round(points * cpp / 100 + taxes, 2)
        depart_time = str(context.get("depart_time", ""))
        arrive_time = str(context.get("arrive_time", ""))
        stops = context.get("stops", "")
        duration_minutes = context.get("duration_minutes", "")

        scoring = score_cash_itinerary(
            effective_usd=effective_usd,
            stops=stops,
            duration_minutes=duration_minutes,
            depart_time=depart_time,
            arrive_time=arrive_time,
            preferences=preferences,
        )
        flags = ["southwest_web_observation", "one_way_only_pricing"]
        brand_flag = fare_brand_flag(price_window)
        if brand_flag:
            flags.append(brand_flag)
        flags.extend(scoring["flags"])
        if status != "observed":
            flags.append(f"status:{status}")

        flight_numbers = str(context.get("flight_numbers", ""))
        key = (flight_numbers, points, taxes, depart_time, arrive_time, request.trip_type)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "origin": request.origin,
                "destination": request.destination,
                "departure_date": request.departure_date,
                "trip_type": "one-way",
                "return_origin": "",
                "return_destination": "",
                "return_date": "",
                "depart_time": depart_time,
                "arrive_time": arrive_time,
                "flight_numbers": flight_numbers,
                "carriers": "WN",
                "cabin": request.cabin,
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
                "duration_display": str(context.get("duration_display", "")),
                "raw_price": f"{points:,} points + ${taxes:g}",
                "raw_text": "\n".join([flight_numbers, price_window]).strip(),
                "status": status,
                "status_message": status_message,
                "created_at": created_at,
            }
        )

    return rows
