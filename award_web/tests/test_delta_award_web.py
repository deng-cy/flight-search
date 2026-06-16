from __future__ import annotations

import sys
import unittest
from pathlib import Path


AWARD_WEB_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = AWARD_WEB_ROOT.parent
for path in (WORKSPACE_ROOT, AWARD_WEB_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from award_web.models import AwardWebSearchRequest
from award_web.normalization import normalize_delta_payload, page_status


PREFERENCES = {
    "points": {
        "default_cents_per_point": 2.0,
        "programs": {"delta": {"label": "Delta SkyMiles", "cents_per_point": 1.2}},
    },
    "ranking": {
        "stop_penalty_usd": 50,
        "duration_penalty_usd_per_hour": 5,
        "next_day_arrival_penalty_usd": 75,
        "time_penalties": {"departure": [], "arrival": []},
    },
}


class DeltaAwardWebTests(unittest.TestCase):
    def test_request_validates_round_trip_return_date(self) -> None:
        with self.assertRaises(ValueError):
            AwardWebSearchRequest(
                origin="SFO",
                destination="DTW",
                departure_date="2026-10-14",
                trip_type="round-trip",
            )

    def test_page_status_captures_delta_error_code(self) -> None:
        status, message = page_status("We're sorry, but there was a problem processing your request. #SFAF009")

        self.assertEqual(status, "provider_error")
        self.assertIn("#SFAF009", message)

    def test_page_status_captures_access_denied(self) -> None:
        status, message = page_status("Access Denied\nYou don't have permission to access this server.\nReference 0.x")

        self.assertEqual(status, "access_denied")
        self.assertIn("Access Denied", message)

    def test_normalizes_conservative_delta_result_text(self) -> None:
        request = AwardWebSearchRequest(
            origin="SFO",
            destination="DTW",
            departure_date="2026-10-14",
        )
        payload = {
            "status": "observed",
            "status_message": "Delta displayed mileage text",
            "created_at": "2026-06-12T00:00:00+00:00",
            "body_text": """
                SFO to DTW
                DL 717
                10:55 AM
                6:25 PM
                Nonstop
                Delta Main
                31,700 miles
                $5.60
                4h 30m
            """,
        }

        rows = normalize_delta_payload(payload, request, Path("/tmp/evidence.png"), PREFERENCES)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source_type"], "web_award")
        self.assertEqual(row["source_name"], "delta")
        self.assertEqual(row["flight_numbers"], "DL717")
        self.assertEqual(row["points"], 31700)
        self.assertEqual(row["taxes_usd"], 5.6)
        self.assertEqual(row["effective_usd"], 386.0)
        self.assertEqual(row["stops"], 0)
        self.assertEqual(row["depart_time"], "10:55")
        self.assertEqual(row["arrive_time"], "18:25")
        self.assertTrue(row["bookable"])

    def test_ignores_mileage_text_without_flight_number(self) -> None:
        request = AwardWebSearchRequest(
            origin="SFO",
            destination="DTW",
            departure_date="2026-10-14",
        )
        payload = {
            "status": "observed",
            "body_text": "Pay with Miles starts at 5,000 miles for eligible card members.",
        }

        rows = normalize_delta_payload(payload, request, Path("/tmp/evidence.png"), PREFERENCES)

        self.assertEqual(rows, [])

    def test_normalizes_delta_split_price_lines(self) -> None:
        request = AwardWebSearchRequest(
            origin="SFO",
            destination="DTW",
            departure_date="2026-10-14",
        )
        payload = {
            "status": "observed",
            "body_text": """
                Nonstop
                DL772
                4h 36m
                6:00am
                1:36pm
                SFO
                DTW
                Delta Main
                Actual Fare
                26,200
                miles
                +
                $
                6
                One-Way
            """,
        }

        rows = normalize_delta_payload(payload, request, Path("/tmp/evidence.png"), PREFERENCES)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["flight_numbers"], "DL772")
        self.assertEqual(rows[0]["points"], 26200)
        self.assertEqual(rows[0]["taxes_usd"], 6.0)
        self.assertEqual(rows[0]["depart_time"], "06:00")


if __name__ == "__main__":
    unittest.main()
