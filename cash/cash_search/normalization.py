from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from flight_search_common.scoring import score_cash_itinerary

from .models import CASH_FIELDNAMES, CashSearchRequest


PRICE_CODE_RE = re.compile(r"\b([A-Z]{3})\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
PRICE_NUMBER_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
SYMBOL_CURRENCIES = (
    ("US$", "USD"),
    ("CA$", "CAD"),
    ("AU$", "AUD"),
    ("NZ$", "NZD"),
    ("HK$", "HKD"),
    ("S$", "SGD"),
    ("$", "USD"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("¥", "JPY"),
)


def parse_price(value: Any, default_currency: str = "USD") -> tuple[float | None, str | None]:
    if value is None:
        return None, None

    text = str(value).strip()
    if not text or text == "0":
        return None, None

    normalized = (
        text.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("from ", "")
        .strip()
    )
    code_match = PRICE_CODE_RE.search(normalized.upper())
    if code_match:
        return float(code_match.group(2).replace(",", "")), code_match.group(1)

    currency = default_currency.upper()
    for symbol, symbol_currency in SYMBOL_CURRENCIES:
        if symbol in normalized:
            currency = symbol_currency
            break

    number_match = PRICE_NUMBER_RE.search(normalized)
    if not number_match:
        return None, currency
    return float(number_match.group(1).replace(",", "")), currency


def normalize_time(value: Any) -> str:
    text = str(value or "").replace("\xa0", " ").replace("\u202f", " ").strip()
    if not text:
        return ""

    compact = " ".join(text.split())
    display_time = re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM)\b", compact, re.IGNORECASE)
    if display_time:
        compact = display_time.group(0)

    for pattern in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            return datetime.strptime(compact.upper(), pattern).strftime("%H:%M")
        except ValueError:
            continue
    return compact


def parse_stops(value: Any) -> int | str:
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        return value

    text = str(value).strip()
    if not text:
        return ""
    if text.lower() == "nonstop":
        return 0

    match = re.search(r"\d+", text)
    if match:
        return int(match.group(0))
    return text


def parse_duration_minutes(value: Any) -> int | str:
    text = str(value or "").lower().replace("\xa0", " ").replace("\u202f", " ").strip()
    if not text:
        return ""

    hours = 0
    minutes = 0

    hour_match = re.search(r"(\d+)\s*(?:hours?|hrs?|h)", text)
    minute_match = re.search(r"(\d+)\s*(?:minutes?|mins?|m)", text)
    compact_match = re.fullmatch(r"(?:(\d+)h)?\s*(?:(\d+)m)?", text.replace(" ", ""))

    if hour_match:
        hours = int(hour_match.group(1))
    if minute_match:
        minutes = int(minute_match.group(1))
    if not hour_match and not minute_match and compact_match:
        hours = int(compact_match.group(1) or 0)
        minutes = int(compact_match.group(2) or 0)

    total = hours * 60 + minutes
    return total if total else ""


def _get(mapping: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return ""


def _mapping_value(mapping: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, dict):
            return value
    return {}


def _leg_route(request: CashSearchRequest, direction: str) -> tuple[str, str, str]:
    if direction == "return":
        return (
            request.return_origin or "",
            request.return_destination or "",
            request.return_date or "",
        )
    return request.origin, request.destination, request.departure_date


def _normalize_cash_leg(
    raw_leg: dict[str, Any],
    request: CashSearchRequest,
    direction: str,
) -> dict[str, Any]:
    origin, destination, date = _leg_route(request, direction)
    raw_leg = raw_leg if isinstance(raw_leg, dict) else {}
    arrival_time_ahead = str(_get(raw_leg, "arrival_time_ahead") or "").strip()
    arrive_time = normalize_time(_get(raw_leg, "arrival", "arrival_time", "arrive_time"))
    if arrival_time_ahead and arrival_time_ahead not in arrive_time:
        arrive_time = f"{arrive_time} {arrival_time_ahead}".strip()

    duration_display = _get(raw_leg, "duration", "duration_display")
    duration_minutes = _get(raw_leg, "duration_minutes")
    if duration_minutes in ("", None):
        duration_minutes = parse_duration_minutes(duration_display)
    segments = []
    for segment in raw_leg.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        segments.append(
            {
                "origin": str(_get(segment, "origin", "from_airport") or ""),
                "destination": str(_get(segment, "destination", "to_airport") or ""),
                "depart_time": normalize_time(_get(segment, "departure", "departure_time", "depart_time")),
                "arrive_time": normalize_time(_get(segment, "arrival", "arrival_time", "arrive_time")),
                "airline": str(_get(segment, "airline", "carrier", "carriers") or ""),
                "flight_number": str(_get(segment, "flight_number", "flight_numbers") or ""),
                "aircraft": str(_get(segment, "aircraft") or ""),
                "duration_minutes": _get(segment, "duration_minutes") or "",
            }
        )
    layovers = []
    for layover in raw_leg.get("layovers") or []:
        if not isinstance(layover, dict):
            continue
        layovers.append(
            {
                "airport": str(_get(layover, "airport", "location") or ""),
                "duration_minutes": _get(layover, "duration_minutes") or "",
                "overnight": bool(layover.get("overnight")),
                "change_of_airport": bool(layover.get("change_of_airport")),
            }
        )
    return {
        "direction": direction,
        "origin": str(_get(raw_leg, "origin", "from_airport") or origin),
        "destination": str(_get(raw_leg, "destination", "to_airport") or destination),
        "date": str(_get(raw_leg, "date", "departure_date") or date),
        "depart_time": normalize_time(_get(raw_leg, "departure", "departure_time", "depart_time")),
        "arrive_time": arrive_time,
        "flight_numbers": _get(raw_leg, "flight_numbers", "flight_number"),
        "carriers": _get(raw_leg, "name", "carrier", "carriers", "airline"),
        "stops": parse_stops(_get(raw_leg, "stops")),
        "duration_minutes": duration_minutes,
        "duration_display": duration_display,
        "segments": segments,
        "layovers": layovers,
    }


def _flight_leg_payloads(flight: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    outbound = _mapping_value(flight, "outbound", "outbound_leg")
    return_leg = _mapping_value(flight, "return", "return_leg", "inbound", "inbound_leg")
    legs = flight.get("legs")
    if isinstance(legs, list):
        leg_mappings = [item for item in legs if isinstance(item, dict)]
        if leg_mappings:
            outbound = outbound or leg_mappings[0]
        if len(leg_mappings) > 1:
            return_leg = return_leg or leg_mappings[1]
    elif isinstance(legs, dict):
        outbound = outbound or _mapping_value(legs, "outbound", "outbound_leg")
        return_leg = return_leg or _mapping_value(legs, "return", "return_leg", "inbound", "inbound_leg")

    return outbound or flight, return_leg


def _leg_has_detail(leg: dict[str, Any]) -> bool:
    detail_fields = (
        "depart_time",
        "arrive_time",
        "flight_numbers",
        "carriers",
        "duration_display",
        "duration_minutes",
    )
    return any(leg.get(field) not in ("", None) for field in detail_fields) or leg.get("stops") not in ("", None)


def _cash_detail_status(legs: dict[str, Any], request: CashSearchRequest, *, bookable: bool) -> str:
    if not bookable:
        return "unavailable"
    outbound_has_detail = _leg_has_detail(legs["outbound"])
    if request.trip_type == "one-way":
        return "complete" if outbound_has_detail else "price_only"
    return_has_detail = _leg_has_detail(legs["return"])
    if outbound_has_detail and return_has_detail:
        return "complete"
    if outbound_has_detail:
        return "outbound_only"
    return "price_only"


def _cash_detail_source(flight: dict[str, Any], status: str) -> str:
    explicit_source = _get(flight, "cash_detail_source", "detail_source")
    if explicit_source:
        return str(explicit_source)
    if status in {"complete", "outbound_only"}:
        return "provider_parser"
    return "none"


def normalize_cash_payload(
    payload: dict[str, Any],
    request: CashSearchRequest,
    evidence_path: Path,
    preferences: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    preferences = preferences or {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    flights = result.get("flights") if isinstance(result.get("flights"), list) else []
    current_price = str(result.get("current_price") or "")

    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for index, flight in enumerate(flights, start=1):
        if not isinstance(flight, dict):
            continue

        raw_price = _get(flight, "price", "raw_price")
        amount, currency = parse_price(raw_price, request.currency)
        is_usd = currency == "USD"
        outbound_raw, return_raw = _flight_leg_payloads(flight)
        legs = {
            "outbound": _normalize_cash_leg(outbound_raw, request, "outbound"),
            "return": _normalize_cash_leg(return_raw, request, "return"),
        }
        stops = legs["outbound"]["stops"]
        duration_display = legs["outbound"]["duration_display"]
        duration_minutes = legs["outbound"]["duration_minutes"]
        depart_time = legs["outbound"]["depart_time"]
        arrive_time = legs["outbound"]["arrive_time"]

        flags = []
        if amount is None:
            flags.append("missing_price")
        if currency and not is_usd:
            flags.append(f"non_usd_price:{currency}")
        if not _get(flight, "name", "carriers"):
            flags.append("missing_carrier")
        if current_price:
            flags.append(f"provider_price_level:{current_price}")

        bookable = amount is not None
        confidence = "medium" if bookable and is_usd else "low"
        cash_detail_status = _cash_detail_status(legs, request, bookable=bookable)
        cash_detail_source = _cash_detail_source(flight, cash_detail_status)
        if request.trip_type != "one-way" and cash_detail_status != "complete":
            flags.append(f"cash_detail:{cash_detail_status}")
        cash_price_usd = round(amount, 2) if amount is not None and is_usd else ""
        effective_usd = cash_price_usd
        scoring = score_cash_itinerary(
            effective_usd=effective_usd,
            stops=stops,
            duration_minutes=duration_minutes,
            depart_time=depart_time,
            arrive_time=arrive_time,
            preferences=preferences,
        )
        for flag in scoring["flags"]:
            if flag not in flags:
                flags.append(flag)

        row = {
            "origin": request.origin,
            "destination": request.destination,
            "departure_date": request.departure_date,
            "trip_type": request.trip_type,
            "return_origin": request.return_origin or "",
            "return_destination": request.return_destination or "",
            "return_date": request.return_date or "",
            "cash_detail_status": cash_detail_status,
            "cash_detail_source": cash_detail_source,
            "legs": legs,
            "outbound_origin": legs["outbound"]["origin"],
            "outbound_destination": legs["outbound"]["destination"],
            "outbound_date": legs["outbound"]["date"],
            "outbound_depart_time": legs["outbound"]["depart_time"],
            "outbound_arrive_time": legs["outbound"]["arrive_time"],
            "outbound_flight_numbers": legs["outbound"]["flight_numbers"],
            "outbound_carriers": legs["outbound"]["carriers"],
            "outbound_stops": legs["outbound"]["stops"],
            "outbound_duration_minutes": legs["outbound"]["duration_minutes"],
            "outbound_duration_display": legs["outbound"]["duration_display"],
            "return_depart_time": legs["return"]["depart_time"],
            "return_arrive_time": legs["return"]["arrive_time"],
            "return_flight_numbers": legs["return"]["flight_numbers"],
            "return_carriers": legs["return"]["carriers"],
            "return_stops": legs["return"]["stops"],
            "return_duration_minutes": legs["return"]["duration_minutes"],
            "return_duration_display": legs["return"]["duration_display"],
            "depart_time": depart_time,
            "arrive_time": arrive_time,
            "flight_numbers": legs["outbound"]["flight_numbers"],
            "carriers": legs["outbound"]["carriers"],
            "cabin": request.cabin,
            "stops": stops,
            "source_type": "cash",
            "source_name": payload.get("provider", "cash"),
            "points": "",
            "cash_price_usd": cash_price_usd,
            "cash_price_amount": round(amount, 2) if amount is not None else "",
            "cash_price_currency": currency or "",
            "taxes_usd": "",
            "effective_usd": effective_usd,
            "bookable": bookable,
            "remaining_seats": "",
            "confidence": confidence,
            "evidence_path": str(evidence_path),
            "stop_penalty_usd": scoring["stop_penalty_usd"],
            "duration_penalty_usd": scoring["duration_penalty_usd"],
            "time_penalty_usd": scoring["time_penalty_usd"],
            "next_day_penalty_usd": scoring["next_day_penalty_usd"],
            "score": scoring["score"],
            "flags": ", ".join(flags),
            "provider_rank": index,
            "provider_is_best": bool(_get(flight, "is_best", "is_best_provider_result")),
            "provider_current_price": current_price,
            "duration_minutes": duration_minutes,
            "duration_display": duration_display,
            "raw_price": raw_price,
            "delay": _get(flight, "delay"),
        }
        dedupe_key = (
            row["trip_type"],
            row["depart_time"],
            row["arrive_time"],
            row["carriers"],
            row["stops"],
            row["return_depart_time"],
            row["return_arrive_time"],
            row["return_carriers"],
            row["return_stops"],
            row["cash_price_amount"],
            row["cash_price_currency"],
            row["duration_minutes"],
            row["return_duration_minutes"],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append({field: row.get(field, "") for field in CASH_FIELDNAMES})

    return sorted(
        rows,
        key=lambda row: (
            row["score"] == "",
            float(row["score"] or 10**9),
            float(row["cash_price_usd"] or 10**9),
            int(row["provider_rank"] or 10**9),
        ),
    )
