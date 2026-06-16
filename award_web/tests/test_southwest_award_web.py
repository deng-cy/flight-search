from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


AWARD_WEB_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = AWARD_WEB_ROOT.parent
for path in (WORKSPACE_ROOT, AWARD_WEB_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from award_web.models import AwardWebSearchRequest
from award_web.southwest.normalization import normalize_southwest_payload, page_status
from award_web.southwest.pipeline import run_pipeline


PREFERENCES = {
    "points": {
        "default_cents_per_point": 2.0,
        "programs": {"southwest": {"label": "Southwest Rapid Rewards", "cents_per_point": 1.35}},
    },
    "ranking": {
        "stop_penalty_usd": 50,
        "duration_penalty_usd_per_hour": 5,
        "next_day_arrival_penalty_usd": 75,
        "time_penalties": {"departure": [], "arrival": []},
    },
}


class SouthwestAwardWebTests(unittest.TestCase):
    def test_page_status_does_not_treat_booking_form_as_results(self) -> None:
        status, message = page_status("Book a Flight\nShow fares in\nPoints\nSearch flights")

        self.assertEqual(status, "search_not_completed")
        self.assertIn("booking form", message)

    def test_normalizes_southwest_result_text(self) -> None:
        request = AwardWebSearchRequest(
            origin="SFO",
            destination="LAS",
            departure_date="2026-06-20",
            source_name="southwest",
        )
        payload = {
            "status": "observed",
            "status_message": "Southwest displayed flight and points text",
            "created_at": "2026-06-14T00:00:00+00:00",
            "body_text": """
                SFO to LAS
                WN 1234
                6:05 AM
                7:45 AM
                Nonstop
                1h 40m
                Basic
                5,228 pts
                $5.60
            """,
        }

        rows = normalize_southwest_payload(payload, request, Path("/tmp/southwest.png"), PREFERENCES)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source_type"], "web_award")
        self.assertEqual(row["source_name"], "southwest")
        self.assertEqual(row["trip_type"], "one-way")
        self.assertEqual(row["flight_numbers"], "WN1234")
        self.assertEqual(row["carriers"], "WN")
        self.assertEqual(row["points"], 5228)
        self.assertEqual(row["taxes_usd"], 5.6)
        self.assertEqual(row["effective_usd"], 76.18)
        self.assertEqual(row["stops"], 0)
        self.assertEqual(row["duration_minutes"], 100)
        self.assertEqual(row["depart_time"], "06:05")
        self.assertEqual(row["arrive_time"], "07:45")
        self.assertIn("one_way_only_pricing", row["flags"])
        self.assertIn("fare_brand:basic", row["flags"])
        self.assertTrue(row["bookable"])

    def test_ignores_marketing_points_without_flight_number(self) -> None:
        request = AwardWebSearchRequest(
            origin="SFO",
            destination="LAS",
            departure_date="2026-06-20",
            source_name="southwest",
        )
        payload = {
            "status": "observed",
            "body_text": "Join Rapid Rewards to earn 2X points on flights. Search flights.",
        }

        rows = normalize_southwest_payload(payload, request, Path("/tmp/southwest.png"), PREFERENCES)

        self.assertEqual(rows, [])

    def test_pipeline_rejects_round_trip_searches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaisesRegex(ValueError, "one-way"):
                run_pipeline(
                    origin="SFO",
                    destination="DTW",
                    departure_date="2026-06-12",
                    trip_type="round-trip",
                    return_date="2026-06-20",
                    output_dir=Path(tmp_dir),
                    preferences_path=WORKSPACE_ROOT / "config/search_preferences.yaml",
                )


if __name__ == "__main__":
    unittest.main()
