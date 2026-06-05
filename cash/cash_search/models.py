from __future__ import annotations

from dataclasses import dataclass


VALID_CABINS = {"economy", "premium-economy", "business", "first"}
VALID_FETCH_MODES = {"common", "fallback", "force-fallback", "local"}
VALID_TRIP_TYPES = {"one-way", "round-trip", "multi-city"}


@dataclass(frozen=True)
class CashSearchRequest:
    origin: str
    destination: str
    departure_date: str
    cabin: str = "economy"
    adults: int = 1
    currency: str = "USD"
    fetch_mode: str = "fallback"
    max_stops: int | None = None
    trip_type: str = "one-way"
    return_date: str | None = None
    return_origin: str | None = None
    return_destination: str | None = None

    def __post_init__(self) -> None:
        origin = self.origin.strip().upper()
        destination = self.destination.strip().upper()
        cabin = self.cabin.strip().lower()
        currency = self.currency.strip().upper()
        fetch_mode = self.fetch_mode.strip().lower()
        trip_type = self.trip_type.strip().lower()
        return_origin = self.return_origin.strip().upper() if self.return_origin else None
        return_destination = self.return_destination.strip().upper() if self.return_destination else None

        if len(origin) != 3 or not origin.isalpha():
            raise ValueError("origin must be a 3-letter IATA airport code")
        if len(destination) != 3 or not destination.isalpha():
            raise ValueError("destination must be a 3-letter IATA airport code")
        if return_origin is not None and (len(return_origin) != 3 or not return_origin.isalpha()):
            raise ValueError("return_origin must be a 3-letter IATA airport code")
        if return_destination is not None and (len(return_destination) != 3 or not return_destination.isalpha()):
            raise ValueError("return_destination must be a 3-letter IATA airport code")
        if cabin not in VALID_CABINS:
            raise ValueError(f"cabin must be one of {sorted(VALID_CABINS)}")
        if self.adults < 1:
            raise ValueError("adults must be at least 1")
        if fetch_mode not in VALID_FETCH_MODES:
            raise ValueError(f"fetch_mode must be one of {sorted(VALID_FETCH_MODES)}")
        if self.max_stops is not None and self.max_stops < 0:
            raise ValueError("max_stops must be zero or greater")
        if trip_type not in VALID_TRIP_TYPES:
            raise ValueError(f"trip_type must be one of {sorted(VALID_TRIP_TYPES)}")
        if trip_type != "one-way":
            if not self.return_date or not return_origin or not return_destination:
                raise ValueError("return_date, return_origin, and return_destination are required for two-leg cash searches")
            if trip_type == "round-trip" and (return_origin != destination or return_destination != origin):
                raise ValueError("round-trip cash searches must return from destination to origin")

        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "cabin", cabin)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "fetch_mode", fetch_mode)
        object.__setattr__(self, "trip_type", trip_type)
        object.__setattr__(self, "return_origin", return_origin)
        object.__setattr__(self, "return_destination", return_destination)

    @property
    def stem(self) -> str:
        cabin_slug = self.cabin.replace("-", "_")
        trip_slug = self.trip_type.replace("-", "_")
        if self.trip_type != "one-way":
            return "_".join(
                [
                    self.origin.lower(),
                    self.destination.lower(),
                    self.departure_date,
                    (self.return_origin or "").lower(),
                    (self.return_destination or "").lower(),
                    self.return_date or "",
                    cabin_slug,
                    trip_slug,
                ]
            )
        return "_".join(
            [
                self.origin.lower(),
                self.destination.lower(),
                self.departure_date,
                cabin_slug,
            ]
        )

    def as_provider_request(self) -> dict[str, object]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "departure_date": self.departure_date,
            "cabin": self.cabin,
            "adults": self.adults,
            "currency": self.currency,
            "fetch_mode": self.fetch_mode,
            "max_stops": self.max_stops,
            "trip_type": self.trip_type,
            "return_date": self.return_date,
            "return_origin": self.return_origin,
            "return_destination": self.return_destination,
        }


CASH_FIELDNAMES = [
    "origin",
    "destination",
    "departure_date",
    "trip_type",
    "return_origin",
    "return_destination",
    "return_date",
    "cash_detail_status",
    "cash_detail_source",
    "legs",
    "outbound_origin",
    "outbound_destination",
    "outbound_date",
    "outbound_depart_time",
    "outbound_arrive_time",
    "outbound_flight_numbers",
    "outbound_carriers",
    "outbound_stops",
    "outbound_duration_minutes",
    "outbound_duration_display",
    "return_depart_time",
    "return_arrive_time",
    "return_flight_numbers",
    "return_carriers",
    "return_stops",
    "return_duration_minutes",
    "return_duration_display",
    "depart_time",
    "arrive_time",
    "flight_numbers",
    "carriers",
    "cabin",
    "stops",
    "source_type",
    "source_name",
    "points",
    "cash_price_usd",
    "cash_price_amount",
    "cash_price_currency",
    "taxes_usd",
    "effective_usd",
    "bookable",
    "remaining_seats",
    "confidence",
    "evidence_path",
    "stop_penalty_usd",
    "duration_penalty_usd",
    "time_penalty_usd",
    "next_day_penalty_usd",
    "score",
    "flags",
    "provider_rank",
    "provider_is_best",
    "provider_current_price",
    "duration_minutes",
    "duration_display",
    "raw_price",
    "delay",
]
