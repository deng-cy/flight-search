from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
for path in (WORKSPACE_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_trip_search
from build_price_summary import combined_rows, top_award_rows
from flight_search_common.web_awards import load_web_award_rows, load_web_round_trip_award_rows
from run_trip_search import (
    CashItineraryContext,
    LegContext,
    award_pair_rows,
    award_web_leg_rows,
    award_web_round_trip_rows,
    recommendation_cards,
)


def sample_web_award_row() -> dict[str, object]:
    return {
        "origin": "SFO",
        "destination": "DTW",
        "departure_date": "2026-10-14",
        "trip_type": "one-way",
        "depart_time": "06:00",
        "arrive_time": "13:36",
        "flight_numbers": "DL772",
        "carriers": "DL",
        "cabin": "economy",
        "stops": 0,
        "source_type": "web_award",
        "source_name": "delta",
        "points": 26200,
        "taxes_usd": 6.0,
        "effective_usd": 320.4,
        "bookable": True,
        "confidence": "medium",
        "evidence_path": "/tmp/delta.png",
        "score": 393.4,
        "duration_minutes": 276,
        "flags": "delta_web_observation",
    }


def sample_round_trip_web_award_row() -> dict[str, object]:
    row = sample_web_award_row()
    row.update(
        {
            "departure_date": "2026-11-13",
            "return_origin": "DTW",
            "return_destination": "SFO",
            "return_date": "2026-11-29",
            "trip_type": "round-trip",
            "points": 86800,
            "taxes_usd": 12.0,
            "effective_usd": 1053.6,
            "score": 1126.6,
            "raw_price": "86,800 miles + $12",
        }
    )
    return row


def sample_round_trip_web_award_row_with_return_timing() -> dict[str, object]:
    row = sample_round_trip_web_award_row()
    outbound_leg = {
        "direction": "outbound",
        "origin": "SFO",
        "destination": "DTW",
        "date": "2026-11-13",
        "depart_time": "14:25",
        "arrive_time": "22:00",
        "flight_numbers": "DL1927",
        "carriers": "DL",
        "stops": 0,
        "duration_minutes": 275,
        "duration_display": "4h 35m",
        "segments": [],
        "layovers": [],
    }
    return_leg = {
        "direction": "return",
        "origin": "DTW",
        "destination": "SFO",
        "date": "2026-11-29",
        "depart_time": "20:20",
        "arrive_time": "22:39",
        "flight_numbers": "DL1327",
        "carriers": "DL",
        "stops": 0,
        "duration_minutes": 319,
        "duration_display": "5h 19m",
        "segments": [],
        "layovers": [],
    }
    row.update(
        {
            "depart_time": "14:25",
            "arrive_time": "22:00",
            "flight_numbers": "DL1927",
            "stops": 0,
            "duration_minutes": 594,
            "duration_display": "4h 35m + 5h 19m",
            "legs": {"outbound": outbound_leg, "return": return_leg},
            "outbound_origin": "SFO",
            "outbound_destination": "DTW",
            "outbound_date": "2026-11-13",
            "outbound_depart_time": "14:25",
            "outbound_arrive_time": "22:00",
            "outbound_flight_numbers": "DL1927",
            "outbound_carriers": "DL",
            "outbound_stops": 0,
            "outbound_duration_minutes": 275,
            "outbound_duration_display": "4h 35m",
            "return_depart_time": "20:20",
            "return_arrive_time": "22:39",
            "return_flight_numbers": "DL1327",
            "return_carriers": "DL",
            "return_stops": 0,
            "return_duration_minutes": 319,
            "return_duration_display": "5h 19m",
            "flags": "delta_web_observation, return_selection_captured",
        }
    )
    return row


def sample_southwest_web_award_row(direction: str) -> dict[str, object]:
    if direction == "outbound":
        origin, destination, date, depart, arrive, flight = "SFO", "DTW", "2026-06-12", "08:00", "15:35", "WN1234 / WN567"
    else:
        origin, destination, date, depart, arrive, flight = "DTW", "SFO", "2026-06-20", "10:15", "14:05", "WN890 / WN456"
    return {
        "origin": origin,
        "destination": destination,
        "departure_date": date,
        "trip_type": "one-way",
        "depart_time": depart,
        "arrive_time": arrive,
        "flight_numbers": flight,
        "carriers": "WN",
        "cabin": "economy",
        "stops": 1,
        "source_type": "web_award",
        "source_name": "southwest",
        "points": 12000 if direction == "outbound" else 15000,
        "taxes_usd": 5.6,
        "effective_usd": 167.6 if direction == "outbound" else 208.1,
        "bookable": True,
        "confidence": "medium",
        "evidence_path": f"/tmp/southwest-{direction}.png",
        "score": 230.0 if direction == "outbound" else 280.0,
        "duration_minutes": 275 if direction == "outbound" else 290,
        "flags": "southwest_web_observation, one_way_only_pricing",
    }


def write_web_rows(root: Path, name: str, rows: list[dict[str, object]]) -> Path:
    path = root / "award_web" / "data" / "normalized" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


class AwardWebIntegrationTests(unittest.TestCase):
    def test_web_award_rows_adapt_to_report_award_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            row = sample_web_award_row()
            write_web_rows(root, "browser_delta_sfo_dtw_2026-10-14_economy_one_way_web_awards.json", [row])
            write_web_rows(root, "delta_sfo_dtw_2026-10-14_economy_one_way_web_awards.json", [row])
            write_web_rows(root, "delta_sfo_dtw_2026-10-14_dtw_sfo_2026-10-21_economy_round_trip_web_awards.json", [row])

            rows = load_web_award_rows(
                root,
                origin="SFO",
                destination="DTW",
                departure_date="2026-10-14",
                cabin="economy",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "delta")
        self.assertEqual(rows[0]["program"], "Delta Web")
        self.assertTrue(rows[0]["comparable"])
        self.assertEqual(rows[0]["mileage_cost"], 26200)
        self.assertEqual(rows[0]["taxes_amount"], 6.0)
        self.assertEqual(rows[0]["cents_per_point"], 1.2)

        summary_rows = combined_rows(cash_rows=[], award_rows=top_award_rows(rows, "economy", 5))
        self.assertEqual(summary_rows[0]["type"], "award")
        self.assertEqual(summary_rows[0]["provider"], "Delta Web")
        self.assertEqual(summary_rows[0]["price"], "DL 26,200 + $6.00")

    def test_trip_report_can_load_cached_web_award_leg_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            write_web_rows(
                root,
                "browser_delta_sfo_dtw_2026-10-14_economy_one_way_web_awards.json",
                [sample_web_award_row()],
            )
            original_root = run_trip_search.WORKSPACE_ROOT
            try:
                run_trip_search.WORKSPACE_ROOT = root
                rows = award_web_leg_rows(
                    [LegContext("outbound", "SFO", "DTW", "2026-10-14")],
                    cabin="economy",
                    per_leg_limit=3,
                )
            finally:
                run_trip_search.WORKSPACE_ROOT = original_root

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "outbound award")
        self.assertEqual(rows[0]["provider"], "Delta Web")
        self.assertEqual(rows[0]["price"], "DL 26,200 + $6.00")
        self.assertEqual(rows[0]["leg_detail"]["program"], "Delta Web")

    def test_trip_report_can_load_cached_round_trip_web_award_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            write_web_rows(
                root,
                "browser_delta_sfo_dtw_2026-11-13_dtw_sfo_2026-11-29_economy_round_trip_web_awards.json",
                [sample_round_trip_web_award_row()],
            )
            rows = load_web_round_trip_award_rows(
                root,
                origin="SFO",
                destination="DTW",
                departure_date="2026-11-13",
                return_origin="DTW",
                return_destination="SFO",
                return_date="2026-11-29",
                cabin="economy",
            )
            original_root = run_trip_search.WORKSPACE_ROOT
            try:
                run_trip_search.WORKSPACE_ROOT = root
                plan_rows = award_web_round_trip_rows(
                    [
                        CashItineraryContext(
                            LegContext("outbound", "SFO", "DTW", "2026-11-13"),
                            LegContext("return", "DTW", "SFO", "2026-11-29"),
                            "round-trip",
                        )
                    ],
                    cabin="economy",
                    per_itinerary_limit=3,
                )
            finally:
                run_trip_search.WORKSPACE_ROOT = original_root

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(plan_rows), 1)
        self.assertEqual(plan_rows[0]["kind"], "web award round-trip")
        self.assertEqual(plan_rows[0]["price"], "DL 86,800 + $12.00")
        self.assertIn("return selection not parsed", plan_rows[0]["notes"])
        self.assertEqual(recommendation_cards(plan_rows), [])

    def test_round_trip_web_award_dedupe_prefers_return_timing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            stale_row = sample_round_trip_web_award_row_with_return_timing()
            stale_row.pop("legs")
            stale_row.update(
                {
                    "return_depart_time": "",
                    "return_arrive_time": "",
                    "return_flight_numbers": "",
                    "return_carriers": "",
                    "return_stops": "",
                    "return_duration_minutes": "",
                    "return_duration_display": "",
                    "flags": "delta_web_observation",
                }
            )
            write_web_rows(
                root,
                "browser_delta_sfo_dtw_2026-11-13_dtw_sfo_2026-11-29_economy_round_trip_web_awards.json",
                [stale_row],
            )
            write_web_rows(
                root,
                "delta_sfo_dtw_2026-11-13_dtw_sfo_2026-11-29_economy_round_trip_web_awards.json",
                [sample_round_trip_web_award_row_with_return_timing()],
            )

            rows = load_web_round_trip_award_rows(
                root,
                origin="SFO",
                destination="DTW",
                departure_date="2026-11-13",
                return_origin="DTW",
                return_destination="SFO",
                return_date="2026-11-29",
                cabin="economy",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["return_depart_time"], "20:20")
        self.assertEqual(rows[0]["return_flight_numbers"], "DL1327")

    def test_trip_report_uses_parsed_round_trip_web_award_return_leg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            write_web_rows(
                root,
                "browser_delta_sfo_dtw_2026-11-13_dtw_sfo_2026-11-29_economy_round_trip_web_awards.json",
                [sample_round_trip_web_award_row_with_return_timing()],
            )
            original_root = run_trip_search.WORKSPACE_ROOT
            try:
                run_trip_search.WORKSPACE_ROOT = root
                plan_rows = award_web_round_trip_rows(
                    [
                        CashItineraryContext(
                            LegContext("outbound", "SFO", "DTW", "2026-11-13"),
                            LegContext("return", "DTW", "SFO", "2026-11-29"),
                            "round-trip",
                        )
                    ],
                    cabin="economy",
                    per_itinerary_limit=3,
                )
            finally:
                run_trip_search.WORKSPACE_ROOT = original_root

        self.assertEqual(len(plan_rows), 1)
        self.assertEqual(plan_rows[0]["return_depart"], "20:20")
        self.assertEqual(plan_rows[0]["return_arrive"], "22:39")
        self.assertIn("20:20 -> 22:39", plan_rows[0]["return_cell"])
        self.assertIn("return details captured", plan_rows[0]["notes"])
        self.assertNotIn("return selection not parsed", plan_rows[0]["notes"])
        self.assertEqual(recommendation_cards(plan_rows), [])

    def test_southwest_web_awards_pair_from_one_ways_and_ignore_round_trip_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            write_web_rows(
                root,
                "southwest_sfo_dtw_2026-06-12_economy_one_way_web_awards.json",
                [sample_southwest_web_award_row("outbound")],
            )
            write_web_rows(
                root,
                "southwest_dtw_sfo_2026-06-20_economy_one_way_web_awards.json",
                [sample_southwest_web_award_row("return")],
            )
            round_trip = sample_southwest_web_award_row("outbound")
            round_trip.update(
                {
                    "trip_type": "round-trip",
                    "return_origin": "DTW",
                    "return_destination": "SFO",
                    "return_date": "2026-06-20",
                }
            )
            write_web_rows(
                root,
                "southwest_sfo_dtw_2026-06-12_dtw_sfo_2026-06-20_economy_round_trip_web_awards.json",
                [round_trip],
            )

            ignored_round_trips = load_web_round_trip_award_rows(
                root,
                origin="SFO",
                destination="DTW",
                departure_date="2026-06-12",
                return_origin="DTW",
                return_destination="SFO",
                return_date="2026-06-20",
                cabin="economy",
            )
            original_root = run_trip_search.WORKSPACE_ROOT
            try:
                run_trip_search.WORKSPACE_ROOT = root
                leg_rows = award_web_leg_rows(
                    [
                        LegContext("outbound", "SFO", "DTW", "2026-06-12"),
                        LegContext("return", "DTW", "SFO", "2026-06-20"),
                    ],
                    cabin="economy",
                    per_leg_limit=3,
                )
            finally:
                run_trip_search.WORKSPACE_ROOT = original_root

        pairs = award_pair_rows(leg_rows, limit=10)

        self.assertEqual(ignored_round_trips, [])
        self.assertEqual(len(leg_rows), 2)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["kind"], "award pair")
        self.assertEqual(pairs[0]["provider"], "Southwest Web / Southwest Web")
        self.assertEqual(pairs[0]["award_points"], 27000)
        self.assertIn("book as two separate awards", pairs[0]["notes"])
        self.assertIn("one way only pricing", pairs[0]["notes"])


if __name__ == "__main__":
    unittest.main()
