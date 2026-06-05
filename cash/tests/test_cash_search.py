from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


CASH_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = CASH_ROOT.parent
for path in (WORKSPACE_ROOT, CASH_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cash_search.models import CashSearchRequest
from cash_search.normalization import (
    normalize_cash_payload,
    parse_duration_minutes,
    parse_price,
)
from cash_search.providers.fli_provider import FliRuntime, search_fli


class CashSearchNormalizationTests(unittest.TestCase):
    def test_parse_usd_prices(self) -> None:
        self.assertEqual(parse_price("$1,234", "USD"), (1234.0, "USD"))
        self.assertEqual(parse_price("USD 87.50", "USD"), (87.5, "USD"))
        self.assertEqual(parse_price("from US$300", "USD"), (300.0, "USD"))

    def test_parse_non_usd_price(self) -> None:
        self.assertEqual(parse_price("CA$450", "USD"), (450.0, "CAD"))

    def test_parse_duration_minutes(self) -> None:
        self.assertEqual(parse_duration_minutes("2 hr 35 min"), 155)
        self.assertEqual(parse_duration_minutes("45 min"), 45)
        self.assertEqual(parse_duration_minutes("3h10m"), 190)

    def test_normalizes_cash_payload(self) -> None:
        request = CashSearchRequest(
            origin="sfo",
            destination="dtw",
            departure_date="2026-10-14",
            cabin="economy",
        )
        payload = {
            "provider": "cash_fixture",
            "result": {
                "current_price": "typical",
                "flights": [
                    {
                        "is_best": True,
                        "name": "Delta",
                        "departure": "2:25 PM",
                        "arrival": "10:00 PM",
                        "arrival_time_ahead": "",
                        "duration": "4 hr 35 min",
                        "stops": "Nonstop",
                        "delay": None,
                        "price": "$310",
                    },
                    {
                        "is_best": False,
                        "name": "Air Canada",
                        "departure": "8:00 AM",
                        "arrival": "6:10 PM",
                        "arrival_time_ahead": "+1",
                        "duration": "7 hr 10 min",
                        "stops": "1 stop",
                        "delay": "Often delayed",
                        "price": "CA$400",
                    },
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            rows = normalize_cash_payload(
                payload,
                request,
                Path(tmp_dir) / "raw.json",
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["carriers"], "Delta")
        self.assertEqual(rows[0]["depart_time"], "14:25")
        self.assertEqual(rows[0]["stops"], 0)
        self.assertEqual(rows[0]["cash_price_usd"], 310.0)
        self.assertEqual(rows[0]["duration_penalty_usd"], 22.92)
        self.assertEqual(rows[0]["score"], 332.92)
        self.assertEqual(rows[0]["flags"], "provider_price_level:typical")

        self.assertEqual(rows[1]["cash_price_usd"], "")
        self.assertEqual(rows[1]["cash_price_currency"], "CAD")
        self.assertIn("non_usd_price:CAD", rows[1]["flags"])
        self.assertEqual(rows[1]["arrive_time"], "18:10 +1")

    def test_normalizes_two_leg_cash_details(self) -> None:
        request = CashSearchRequest(
            origin="SFO",
            destination="FCA",
            departure_date="2026-09-04",
            trip_type="round-trip",
            return_date="2026-09-07",
            return_origin="FCA",
            return_destination="SFO",
        )
        payload = {
            "provider": "cash_fixture",
            "result": {
                "flights": [
                    {
                        "price": "$450",
                        "legs": [
                            {
                                "carrier": "United",
                                "departure": "9:00 AM",
                                "arrival": "2:10 PM",
                                "duration": "4 hr 10 min",
                                "stops": "1 stop",
                                "flight_numbers": "UA 100 / UA 200",
                            },
                            {
                                "carrier": "United",
                                "departure": "10:15 AM",
                                "arrival": "1:20 PM",
                                "duration": "4 hr 5 min",
                                "stops": "1 stop",
                                "flight_numbers": "UA 201 / UA 101",
                            },
                        ],
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            rows = normalize_cash_payload(payload, request, Path(tmp_dir) / "raw.json")

        self.assertEqual(rows[0]["cash_detail_status"], "complete")
        self.assertEqual(rows[0]["cash_detail_source"], "provider_parser")
        self.assertEqual(rows[0]["outbound_depart_time"], "09:00")
        self.assertEqual(rows[0]["return_depart_time"], "10:15")
        self.assertEqual(rows[0]["return_arrive_time"], "13:20")
        self.assertEqual(rows[0]["legs"]["return"]["flight_numbers"], "UA 201 / UA 101")
        self.assertNotIn("cash_detail:", rows[0]["flags"])

    def test_marks_round_trip_cash_when_return_details_are_missing(self) -> None:
        request = CashSearchRequest(
            origin="SFO",
            destination="MSO",
            departure_date="2026-09-04",
            trip_type="round-trip",
            return_date="2026-09-07",
            return_origin="MSO",
            return_destination="SFO",
        )
        payload = {
            "provider": "cash_fixture",
            "result": {
                "flights": [
                    {
                        "name": "Delta",
                        "departure": "10:00 AM",
                        "arrival": "5:23 PM on Fri, Sep 4",
                        "duration": "6 hr 23 min",
                        "stops": 1,
                        "price": "$289",
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            rows = normalize_cash_payload(payload, request, Path(tmp_dir) / "raw.json")

        self.assertEqual(rows[0]["cash_detail_status"], "outbound_only")
        self.assertEqual(rows[0]["return_origin"], "MSO")
        self.assertEqual(rows[0]["return_destination"], "SFO")
        self.assertEqual(rows[0]["return_depart_time"], "")
        self.assertIn("cash_detail:outbound_only", rows[0]["flags"])

    def test_normalizes_fli_payload_with_complete_return_details(self) -> None:
        request = CashSearchRequest(
            origin="SFO",
            destination="MSO",
            departure_date="2026-09-04",
            trip_type="round-trip",
            return_date="2026-09-07",
            return_origin="MSO",
            return_destination="SFO",
        )
        payload = {
            "provider": "fli",
            "result": {
                "flights": [
                    {
                        "price": "USD 289.00",
                        "cash_detail_source": "fli",
                        "legs": [
                            {
                                "carrier": "DL",
                                "departure": "17:10",
                                "arrival": "00:18",
                                "arrival_time_ahead": "+1",
                                "duration": "6h 8m",
                                "stops": 1,
                                "flight_numbers": "DL 1088 / DL 1723",
                            },
                            {
                                "carrier": "DL",
                                "departure": "05:30",
                                "arrival": "08:50",
                                "duration": "4h 20m",
                                "stops": 1,
                                "flight_numbers": "DL 2795 / DL 920",
                            },
                        ],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            rows = normalize_cash_payload(payload, request, Path(tmp_dir) / "raw.json")

        self.assertEqual(rows[0]["source_name"], "fli")
        self.assertEqual(rows[0]["cash_detail_status"], "complete")
        self.assertEqual(rows[0]["cash_detail_source"], "fli")
        self.assertEqual(rows[0]["outbound_arrive_time"], "00:18 +1")
        self.assertEqual(rows[0]["return_depart_time"], "05:30")
        self.assertEqual(rows[0]["return_flight_numbers"], "DL 2795 / DL 920")

    def test_round_trip_fli_provider_call_uses_two_segments(self) -> None:
        calls = []

        class DummyModel:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class DummySearchFlights:
            def search(self, filters, **kwargs):
                calls.append({"filters": filters, "kwargs": kwargs})
                return []

        runtime = FliRuntime(
            SearchFlights=DummySearchFlights,
            FlightSearchFilters=DummyModel,
            PassengerInfo=DummyModel,
            MaxStops=SimpleNamespace(
                ANY="ANY",
                NON_STOP="NON_STOP",
                ONE_STOP_OR_FEWER="ONE_STOP",
                TWO_OR_FEWER_STOPS="TWO",
            ),
            SeatType=SimpleNamespace(ECONOMY="ECONOMY"),
            SortBy=SimpleNamespace(CHEAPEST="CHEAPEST"),
            TripType=SimpleNamespace(
                ONE_WAY="one-way",
                ROUND_TRIP="round-trip",
                MULTI_CITY="multi-city",
            ),
            FlightSegment=DummyModel,
            resolve_airport=lambda code: code,
        )
        request = CashSearchRequest(
            origin="SFO",
            destination="FCA",
            departure_date="2026-09-04",
            trip_type="round-trip",
            return_date="2026-09-07",
            return_origin="FCA",
            return_destination="SFO",
        )

        with patch("cash_search.providers.fli_provider._load_fli", return_value=runtime):
            search_fli(request)

        filters = calls[0]["filters"]
        segments = filters.kwargs["flight_segments"]
        self.assertEqual(filters.kwargs["trip_type"], "round-trip")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].kwargs["departure_airport"], [["SFO", 0]])
        self.assertEqual(segments[1].kwargs["departure_airport"], [["FCA", 0]])

    def test_multi_city_fli_provider_call_uses_open_jaw_segments(self) -> None:
        calls = []

        class DummyModel:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class DummySearchFlights:
            def search(self, filters, **kwargs):
                calls.append({"filters": filters, "kwargs": kwargs})
                return []

        runtime = FliRuntime(
            SearchFlights=DummySearchFlights,
            FlightSearchFilters=DummyModel,
            PassengerInfo=DummyModel,
            MaxStops=SimpleNamespace(
                ANY="ANY",
                NON_STOP="NON_STOP",
                ONE_STOP_OR_FEWER="ONE_STOP",
                TWO_OR_FEWER_STOPS="TWO",
            ),
            SeatType=SimpleNamespace(ECONOMY="ECONOMY"),
            SortBy=SimpleNamespace(CHEAPEST="CHEAPEST"),
            TripType=SimpleNamespace(
                ONE_WAY="one-way",
                ROUND_TRIP="round-trip",
                MULTI_CITY="multi-city",
            ),
            FlightSegment=DummyModel,
            resolve_airport=lambda code: code,
        )
        request = CashSearchRequest(
            origin="SFO",
            destination="FCA",
            departure_date="2026-09-04",
            trip_type="multi-city",
            return_date="2026-09-07",
            return_origin="MSO",
            return_destination="SJC",
        )

        with patch("cash_search.providers.fli_provider._load_fli", return_value=runtime):
            search_fli(request)

        filters = calls[0]["filters"]
        segments = filters.kwargs["flight_segments"]
        self.assertEqual(filters.kwargs["trip_type"], "multi-city")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[1].kwargs["departure_airport"], [["MSO", 0]])
        self.assertEqual(segments[1].kwargs["arrival_airport"], [["SJC", 0]])


if __name__ == "__main__":
    unittest.main()
