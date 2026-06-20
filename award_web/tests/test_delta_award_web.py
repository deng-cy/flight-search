from __future__ import annotations

import json
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
from award_web.normalization import normalize_delta_payload, page_status
from award_web.delta.pipeline import run_pipeline
from award_web.delta.provider import import_delta_browser_capture


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

    def test_round_trip_snapshots_capture_return_leg_timing(self) -> None:
        request = AwardWebSearchRequest(
            origin="SFO",
            destination="DTW",
            departure_date="2026-11-13",
            trip_type="round-trip",
            return_origin="DTW",
            return_destination="SFO",
            return_date="2026-11-29",
        )
        payload = {
            "status": "observed",
            "status_message": "Delta displayed mileage text",
            "created_at": "2026-06-12T00:00:00+00:00",
            "snapshots": [
                {
                    "stage": "outbound",
                    "status": "observed",
                    "body_text": """
                        Outbound
                        SFO
                        DTW
                        DL1927
                        4h 35m
                        2:25pm
                        10:00pm
                        SFO
                        DTW
                        Delta Main Classic
                        Actual Fare
                        86,800
                        miles
                        +
                        $
                        12
                        Round Trip
                    """,
                    "evidence": {"screenshot": "/tmp/outbound.png"},
                },
                {
                    "stage": "return",
                    "status": "observed",
                    "body_text": """
                        Return
                        DTW
                        SFO
                        DL1327
                        5h 19m
                        8:20pm
                        10:39pm
                        DTW
                        SFO
                        Delta Main Classic
                        Actual Fare
                        86,800
                        miles
                        +
                        $
                        12
                        Round Trip
                    """,
                    "evidence": {"screenshot": "/tmp/return.png"},
                },
            ],
        }

        rows = normalize_delta_payload(payload, request, Path("/tmp/evidence.png"), PREFERENCES)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["depart_time"], "14:25")
        self.assertEqual(row["arrive_time"], "22:00")
        self.assertEqual(row["flight_numbers"], "DL1927")
        self.assertEqual(row["outbound_depart_time"], "14:25")
        self.assertEqual(row["outbound_arrive_time"], "22:00")
        self.assertEqual(row["return_depart_time"], "20:20")
        self.assertEqual(row["return_arrive_time"], "22:39")
        self.assertEqual(row["return_flight_numbers"], "DL1327")
        self.assertEqual(row["duration_minutes"], 594)
        self.assertEqual(row["duration_display"], "4h 35m + 5h 19m")
        self.assertEqual(row["legs"]["return"]["depart_time"], "20:20")
        self.assertIn("return_selection_captured", row["flags"])

    def test_imports_browser_session_capture_snapshots(self) -> None:
        request = AwardWebSearchRequest(
            origin="SFO",
            destination="DTW",
            departure_date="2026-11-13",
            trip_type="round-trip",
            return_origin="DTW",
            return_destination="SFO",
            return_date="2026-11-29",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            capture_path = root / "delta_browser_capture.json"
            html_path = root / "raw" / f"{request.stem}.html"
            screenshot_path = root / "raw" / f"{request.stem}.png"
            capture_path.write_text(
                json.dumps(
                    {
                        "created_at": "2026-06-19T00:00:00+00:00",
                        "snapshots": [
                            {
                                "stage": "outbound",
                                "url": "https://www.delta.com/outbound",
                                "html_content": "<html><body>outbound</body></html>",
                                "body_text": """
                                    Outbound
                                    SFO
                                    DTW
                                    DL1927
                                    4h 35m
                                    2:25pm
                                    10:00pm
                                    Delta Main Classic
                                    Actual Fare
                                    86,800
                                    miles
                                    +
                                    $
                                    12
                                    Round Trip
                                """,
                            },
                            {
                                "stage": "return",
                                "url": "https://www.delta.com/return",
                                "html_content": "<html><body>return</body></html>",
                                "body_text": """
                                    Return
                                    DTW
                                    SFO
                                    DL1327
                                    5h 19m
                                    8:20pm
                                    10:39pm
                                    Delta Main Classic
                                    Actual Fare
                                    86,800
                                    miles
                                    +
                                    $
                                    12
                                    Round Trip
                                """,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = import_delta_browser_capture(
                capture_path,
                request,
                html_path=html_path,
                screenshot_path=screenshot_path,
            )
            final_html = Path(payload["evidence"]["html"]).read_text(encoding="utf-8")

        self.assertEqual(payload["capture_source"], "browser_session")
        self.assertEqual(payload["url"], "https://www.delta.com/return")
        self.assertEqual(len(payload["snapshots"]), 2)
        self.assertTrue(payload["snapshots"][0]["evidence"]["html"].endswith("_outbound.html"))
        self.assertEqual(final_html, "<html><body>return</body></html>")

        rows = normalize_delta_payload(payload, request, Path(payload["evidence"]["html"]), PREFERENCES)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["return_depart_time"], "20:20")
        self.assertEqual(rows[0]["return_arrive_time"], "22:39")

    def test_pipeline_normalizes_browser_capture_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "data"
            preferences_path = root / "preferences.yaml"
            preferences_path.write_text(
                """
points:
  default_cents_per_point: 2.0
  programs:
    delta:
      label: Delta SkyMiles
      cents_per_point: 1.2
ranking:
  stop_penalty_usd: 50
  duration_penalty_usd_per_hour: 5
  next_day_arrival_penalty_usd: 75
  time_penalties:
    departure: []
    arrival: []
""".lstrip(),
                encoding="utf-8",
            )
            capture_path = root / "delta_browser_capture.json"
            capture_path.write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "stage": "outbound",
                                "body_text": "Outbound\nSFO\nDTW\nDL1927\n4h 35m\n2:25pm\n10:00pm\n86,800\nmiles\n$\n12",
                            },
                            {
                                "stage": "return",
                                "body_text": "Return\nDTW\nSFO\nDL1327\n5h 19m\n8:20pm\n10:39pm\n86,800\nmiles\n$\n12",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = run_pipeline(
                origin="SFO",
                destination="DTW",
                departure_date="2026-11-13",
                trip_type="round-trip",
                return_origin="DTW",
                return_destination="SFO",
                return_date="2026-11-29",
                output_dir=output_dir,
                preferences_path=preferences_path,
                browser_capture_path=capture_path,
            )

            normalized = json.loads(Path(summary["outputs"]["normalized_json"]).read_text(encoding="utf-8"))
            raw_payload = json.loads(Path(summary["raw_response"]).read_text(encoding="utf-8"))

        self.assertEqual(summary["capture_source"], "browser_session")
        self.assertEqual(summary["normalized_count"], 1)
        self.assertEqual(raw_payload["capture_source"], "browser_session")
        self.assertEqual(normalized[0]["return_depart_time"], "20:20")


if __name__ == "__main__":
    unittest.main()
