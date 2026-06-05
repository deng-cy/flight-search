from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from typing import Any

from cash_search.models import CashSearchRequest


class ProviderUnavailableError(RuntimeError):
    """Raised when the optional provider dependency is not installed."""


@dataclass(frozen=True)
class FliRuntime:
    SearchFlights: Any
    FlightSearchFilters: Any
    PassengerInfo: Any
    MaxStops: Any
    SeatType: Any
    SortBy: Any
    TripType: Any
    FlightSegment: Any
    resolve_airport: Any


def _load_fli() -> FliRuntime:
    try:
        from fli.core import resolve_airport
        from fli.models import (
            FlightSearchFilters,
            FlightSegment,
            MaxStops,
            PassengerInfo,
            SeatType,
            SortBy,
        )
        from fli.models.google_flights.base import TripType
        from fli.search import SearchFlights
    except ImportError as exc:
        raise ProviderUnavailableError(
            "Install cash/requirements.txt with Python 3.10+ before running live cash searches "
            "(the flights/fli package requires Python >=3.10)."
        ) from exc

    return FliRuntime(
        SearchFlights=SearchFlights,
        FlightSearchFilters=FlightSearchFilters,
        PassengerInfo=PassengerInfo,
        MaxStops=MaxStops,
        SeatType=SeatType,
        SortBy=SortBy,
        TripType=TripType,
        FlightSegment=FlightSegment,
        resolve_airport=resolve_airport,
    )


def _package_version() -> str:
    try:
        return metadata.version("flights")
    except metadata.PackageNotFoundError:
        return "unknown"


def _airport_code(airport: Any) -> str:
    return getattr(airport, "name", str(airport)).removeprefix("_")


def _airline_code(airline: Any) -> str:
    return getattr(airline, "name", str(airline)).removeprefix("_")


def _format_time(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value or "")


def _format_date(value: Any, fallback: str) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return fallback


def _arrival_time_ahead(segment: Any) -> str:
    if not getattr(segment, "legs", None):
        return ""
    first = segment.legs[0].departure_datetime
    last = segment.legs[-1].arrival_datetime
    if not hasattr(first, "date") or not hasattr(last, "date"):
        return ""
    day_delta = (last.date() - first.date()).days
    return f"+{day_delta}" if day_delta > 0 else ""


def _duration_display(minutes: int | None) -> str:
    if not minutes:
        return ""
    hours, remainder = divmod(int(minutes), 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def _seat_type(cabin: str, runtime: FliRuntime) -> Any:
    cabin_key = cabin.replace("-", "_").upper()
    return getattr(runtime.SeatType, cabin_key)


def _max_stops(max_stops: int | None, runtime: FliRuntime) -> Any:
    if max_stops is None:
        return runtime.MaxStops.ANY
    if max_stops <= 0:
        return runtime.MaxStops.NON_STOP
    if max_stops == 1:
        return runtime.MaxStops.ONE_STOP_OR_FEWER
    return runtime.MaxStops.TWO_OR_FEWER_STOPS


def _flight_segment(
    runtime: FliRuntime,
    origin: str,
    destination: str,
    date: str,
) -> Any:
    return runtime.FlightSegment(
        departure_airport=[[runtime.resolve_airport(origin), 0]],
        arrival_airport=[[runtime.resolve_airport(destination), 0]],
        travel_date=date,
    )


def _build_filters(request: CashSearchRequest, runtime: FliRuntime) -> Any:
    if request.trip_type == "one-way":
        trip_type = runtime.TripType.ONE_WAY
        segments = [
            _flight_segment(runtime, request.origin, request.destination, request.departure_date)
        ]
    elif request.trip_type == "round-trip":
        trip_type = runtime.TripType.ROUND_TRIP
        segments = [
            _flight_segment(runtime, request.origin, request.destination, request.departure_date),
            _flight_segment(
                runtime,
                request.return_origin or request.destination,
                request.return_destination or request.origin,
                request.return_date or "",
            ),
        ]
    else:
        trip_type = runtime.TripType.MULTI_CITY
        segments = [
            _flight_segment(runtime, request.origin, request.destination, request.departure_date),
            _flight_segment(
                runtime,
                request.return_origin or request.destination,
                request.return_destination or request.origin,
                request.return_date or "",
            ),
        ]

    return runtime.FlightSearchFilters(
        trip_type=trip_type,
        passenger_info=runtime.PassengerInfo(adults=request.adults),
        flight_segments=segments,
        stops=_max_stops(request.max_stops, runtime),
        seat_type=_seat_type(request.cabin, runtime),
        sort_by=runtime.SortBy.CHEAPEST,
    )


def _segment_payload(segment: Any, *, direction: str, route_date: str) -> dict[str, Any]:
    legs = list(getattr(segment, "legs", []) or [])
    first_leg = legs[0] if legs else None
    last_leg = legs[-1] if legs else None
    carriers = []
    flight_numbers = []
    for leg in legs:
        carrier = _airline_code(leg.airline)
        if carrier not in carriers:
            carriers.append(carrier)
        flight_number = f"{carrier} {leg.flight_number}".strip()
        if flight_number:
            flight_numbers.append(flight_number)

    return {
        "direction": direction,
        "origin": _airport_code(first_leg.departure_airport) if first_leg else "",
        "destination": _airport_code(last_leg.arrival_airport) if last_leg else "",
        "date": _format_date(first_leg.departure_datetime, route_date) if first_leg else route_date,
        "departure": _format_time(first_leg.departure_datetime) if first_leg else "",
        "arrival": _format_time(last_leg.arrival_datetime) if last_leg else "",
        "arrival_time_ahead": _arrival_time_ahead(segment),
        "duration": _duration_display(getattr(segment, "duration", None)),
        "duration_minutes": getattr(segment, "duration", ""),
        "stops": getattr(segment, "stops", ""),
        "carrier": ", ".join(carriers),
        "flight_numbers": " / ".join(flight_numbers),
        "segments": [
            {
                "airline": _airline_code(leg.airline),
                "flight_number": leg.flight_number,
                "origin": _airport_code(leg.departure_airport),
                "destination": _airport_code(leg.arrival_airport),
                "depart_time": _format_time(leg.departure_datetime),
                "arrive_time": _format_time(leg.arrival_datetime),
                "depart_datetime": leg.departure_datetime.isoformat(),
                "arrive_datetime": leg.arrival_datetime.isoformat(),
                "duration_minutes": leg.duration,
                "aircraft": getattr(leg, "aircraft", None),
                "operating_airline": _airline_code(leg.operating_airline)
                if getattr(leg, "operating_airline", None)
                else "",
                "operating_flight_number": getattr(leg, "operating_flight_number", "") or "",
            }
            for leg in legs
        ],
        "layovers": [
            {
                "airport": _airport_code(layover.airport),
                "duration_minutes": layover.duration,
                "overnight": layover.overnight,
                "change_of_airport": layover.change_of_airport,
            }
            for layover in (getattr(segment, "layovers", None) or [])
        ],
    }


def _price_segment(segments: list[Any]) -> Any:
    # Live booking checks showed fli's final selected segment carries the
    # complete fare for round-trip and open-jaw pairs. The original outbound
    # can remain a broad "from" price after return choices are expanded.
    return segments[-1]


def _flight_payload(result: Any, request: CashSearchRequest, rank: int) -> dict[str, Any]:
    segments = list(result) if isinstance(result, tuple) else [result]
    price_segment = _price_segment(segments)
    outbound = segments[0]
    return_leg = segments[1] if len(segments) > 1 else None
    price = getattr(price_segment, "price", None)
    currency = getattr(price_segment, "currency", None) or request.currency
    raw_price = f"{currency} {price:.2f}" if price is not None else ""
    outbound_payload = _segment_payload(
        outbound,
        direction="outbound",
        route_date=request.departure_date,
    )

    payload = {
        "is_best": rank == 1,
        "carriers": outbound_payload["carrier"],
        "price": raw_price,
        "cash_detail_source": "fli",
        "legs": [outbound_payload],
    }
    if return_leg is not None:
        payload["legs"].append(
            _segment_payload(
                return_leg,
                direction="return",
                route_date=request.return_date or "",
            )
        )
    return payload


def _base_payload(request: CashSearchRequest) -> dict[str, Any]:
    return {
        "provider": "fli",
        "provider_package": "flights",
        "provider_version": _package_version(),
        "provider_api_variant": "python-api",
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "request": request.as_provider_request(),
    }


def search_fli(request: CashSearchRequest) -> dict[str, Any]:
    runtime = _load_fli()
    filters = _build_filters(request, runtime)
    top_n = int(os.environ.get("FLI_TOP_N", "3"))
    payload = _base_payload(request)
    try:
        results = runtime.SearchFlights().search(
            filters,
            top_n=top_n,
            currency=request.currency,
            language="en",
            country="US",
        )
    except Exception as exc:  # noqa: BLE001 - provider failures should be captured.
        payload.update(
            {
                "provider_error": str(exc),
                "result": {"current_price": "", "flights": []},
            }
        )
        return payload

    payload.update(
        {
            "result": {
                "current_price": "",
                "flights": [
                    _flight_payload(result, request, rank)
                    for rank, result in enumerate(results or [], start=1)
                ],
            },
            "evidence": {
                "transport": "fli",
                "top_n": top_n,
                "result_count": len(results or []),
            },
        }
    )
    return payload
