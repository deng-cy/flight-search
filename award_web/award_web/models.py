from __future__ import annotations

from dataclasses import dataclass
from datetime import date


VALID_CABINS = {"economy", "premium-economy", "business", "first"}
VALID_TRIP_TYPES = {"one-way", "round-trip"}


@dataclass(frozen=True)
class AwardWebSearchRequest:
    origin: str
    destination: str
    departure_date: str
    cabin: str = "economy"
    adults: int = 1
    trip_type: str = "one-way"
    return_date: str | None = None
    return_origin: str | None = None
    return_destination: str | None = None
    source_name: str = "delta"

    def __post_init__(self) -> None:
        origin = self.origin.strip().upper()
        destination = self.destination.strip().upper()
        cabin = self.cabin.strip().lower()
        trip_type = self.trip_type.strip().lower()
        return_origin = (self.return_origin or destination).strip().upper() if self.return_date else None
        return_destination = (self.return_destination or origin).strip().upper() if self.return_date else None
        source_name = self.source_name.strip().lower()

        if len(origin) != 3 or not origin.isalpha():
            raise ValueError("origin must be a 3-letter IATA airport code")
        if len(destination) != 3 or not destination.isalpha():
            raise ValueError("destination must be a 3-letter IATA airport code")
        if cabin not in VALID_CABINS:
            raise ValueError(f"cabin must be one of {sorted(VALID_CABINS)}")
        if self.adults < 1:
            raise ValueError("adults must be at least 1")
        if trip_type not in VALID_TRIP_TYPES:
            raise ValueError(f"trip_type must be one of {sorted(VALID_TRIP_TYPES)}")
        if trip_type == "round-trip" and not self.return_date:
            raise ValueError("return_date is required for round-trip award web searches")
        if trip_type == "one-way" and self.return_date:
            raise ValueError("return_date requires trip_type=round-trip")

        date.fromisoformat(self.departure_date)
        if self.return_date:
            date.fromisoformat(self.return_date)
            if not return_origin or len(return_origin) != 3 or not return_origin.isalpha():
                raise ValueError("return_origin must be a 3-letter IATA airport code")
            if not return_destination or len(return_destination) != 3 or not return_destination.isalpha():
                raise ValueError("return_destination must be a 3-letter IATA airport code")

        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "cabin", cabin)
        object.__setattr__(self, "trip_type", trip_type)
        object.__setattr__(self, "return_origin", return_origin)
        object.__setattr__(self, "return_destination", return_destination)
        object.__setattr__(self, "source_name", source_name)

    @property
    def stem(self) -> str:
        cabin_slug = self.cabin.replace("-", "_")
        trip_slug = self.trip_type.replace("-", "_")
        parts = [
            self.source_name,
            self.origin.lower(),
            self.destination.lower(),
            self.departure_date,
        ]
        if self.trip_type == "round-trip":
            parts.extend(
                [
                    (self.return_origin or "").lower(),
                    (self.return_destination or "").lower(),
                    self.return_date or "",
                ]
            )
        parts.extend([cabin_slug, trip_slug])
        return "_".join(parts)

    def as_provider_request(self) -> dict[str, object]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "departure_date": self.departure_date,
            "cabin": self.cabin,
            "adults": self.adults,
            "trip_type": self.trip_type,
            "return_date": self.return_date,
            "return_origin": self.return_origin,
            "return_destination": self.return_destination,
            "source_name": self.source_name,
        }


AWARD_WEB_FIELDNAMES = [
    "origin",
    "destination",
    "departure_date",
    "trip_type",
    "return_origin",
    "return_destination",
    "return_date",
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
    "seat_credit_usd",
    "score",
    "flags",
    "duration_minutes",
    "duration_display",
    "raw_price",
    "raw_text",
    "status",
    "status_message",
    "created_at",
]
