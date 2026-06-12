from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
for path in (WORKSPACE_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_trip_search import (
    annotate_cash_strategy_comparisons,
    award_pair_rows,
    cash_one_way_pair_rows,
    choose_cash_trip_type,
    expand_trip_search,
    leg_stop_value,
    mixed_cash_award_rows,
    recommendation_cards,
    run_ordered_workers,
    write_master_html,
)


class TripSearchExpansionTests(unittest.TestCase):
    def test_fca_mso_expansion_counts(self) -> None:
        plan = expand_trip_search(
            origins=["SFO", "SJC"],
            destinations=["FCA", "MSO"],
            outbound_dates=["2026-09-04", "2026-09-05"],
            return_dates=["2026-09-07"],
        )

        self.assertEqual(len(plan.outbound_legs), 8)
        self.assertEqual(len(plan.return_legs), 4)
        self.assertEqual(len(plan.cash_one_way_legs), 12)
        self.assertEqual(len(plan.cash_itineraries), 32)

        round_trips = [item for item in plan.cash_itineraries if item.trip_type == "round-trip"]
        multi_city = [item for item in plan.cash_itineraries if item.trip_type == "multi-city"]
        self.assertEqual(len(round_trips), 8)
        self.assertEqual(len(multi_city), 24)

    def test_dtw_expansion_counts(self) -> None:
        plan = expand_trip_search(
            origins=["SFO", "SJC"],
            destinations=["DTW"],
            outbound_dates=["2026-11-13", "2026-11-14"],
            return_dates=["2026-11-29", "2026-11-30"],
        )

        self.assertEqual(len(plan.outbound_legs), 4)
        self.assertEqual(len(plan.return_legs), 4)
        self.assertEqual(len(plan.cash_one_way_legs), 8)
        self.assertEqual(len(plan.cash_itineraries), 16)

        round_trips = [item for item in plan.cash_itineraries if item.trip_type == "round-trip"]
        multi_city = [item for item in plan.cash_itineraries if item.trip_type == "multi-city"]
        self.assertEqual(len(round_trips), 8)
        self.assertEqual(len(multi_city), 8)

    def test_cash_trip_type_selection(self) -> None:
        plan = expand_trip_search(
            origins=["SFO"],
            destinations=["FCA", "MSO"],
            outbound_dates=["2026-09-04"],
            return_dates=["2026-09-07"],
        )
        exact_reverse = plan.cash_itineraries[0]
        open_jaw = next(item for item in plan.cash_itineraries if item.return_leg.origin != item.outbound.destination)

        self.assertEqual(choose_cash_trip_type(exact_reverse.outbound, exact_reverse.return_leg), "round-trip")
        self.assertEqual(choose_cash_trip_type(open_jaw.outbound, open_jaw.return_leg), "multi-city")

    def test_ordered_workers_preserve_input_order(self) -> None:
        self.assertEqual(
            run_ordered_workers([3, 1, 2], workers=3, runner=lambda value: value * 10),
            [30, 10, 20],
        )

    def test_master_report_renders_complete_and_award_sections(self) -> None:
        plan = expand_trip_search(
            origins=["SFO"],
            destinations=["FCA"],
            outbound_dates=["2026-09-04"],
            return_dates=["2026-09-07"],
        )
        complete_rows = [
            {
                "kind": "cash",
                "route": "SFO -> FCA / FCA -> SFO",
                "dates": "2026-09-04 / 2026-09-07",
                "origin": "SFO",
                "destination": "FCA",
                "outbound_date": "2026-09-04",
                "return_origin": "FCA",
                "return_destination": "SFO",
                "return_date": "2026-09-07",
                "same_airports": True,
                "trip_type": "round-trip",
                "cash_detail_status": "complete",
                "cash_detail_source": "fli",
                "price": "$450.00",
                "effective": "$450.00",
                "effective_num": 450.0,
                "score": 520.0,
                "score_label": "520.00",
                "stops": "2 + 1",
                "stops_num": 3,
                "duration": "9h",
                "duration_minutes": 540,
                "depart": "09:00 / 10:15",
                "arrive": "15:00 / 13:20",
                "outbound_depart": "09:00",
                "outbound_arrive": "15:00",
                "return_depart": "10:15",
                "return_arrive": "13:20",
                "provider": "cash",
                "notes": "round trip cash fare",
                "outbound_cell": "SFO -> FCA\n2026-09-04\n09:00 -> 15:00\nUnited, 1 stop(s), 4h 30m",
                "return_cell": "FCA -> SFO\n2026-09-07\n10:15 -> 13:20\nUnited, 1 stop(s), 4h 30m",
            }
        ]
        award_rows = [
            {
                "kind": "outbound award",
                "direction": "outbound",
                "route": "SFO -> FCA",
                "dates": "2026-09-04",
                "trip_type": "award one-way",
                "price": "UA 12,500 + $5.60",
                "effective": "$155.60",
                "effective_num": 155.60,
                "score": 205.0,
                "score_label": "205.00",
                "stops": "1",
                "stops_num": 1,
                "duration": "5h",
                "duration_minutes": 300,
                "depart": "08:00",
                "arrive": "13:00",
                "provider": "United",
                "notes": "early departure",
                "leg": {"origin": "SFO", "destination": "FCA"},
            },
            {
                "kind": "return award",
                "direction": "return",
                "route": "FCA -> SFO",
                "dates": "2026-09-07",
                "trip_type": "award one-way",
                "price": "UA 12,500 + $5.60",
                "effective": "$155.60",
                "effective_num": 155.60,
                "score": 210.0,
                "score_label": "210.00",
                "stops": "1",
                "stops_num": 1,
                "duration": "5h",
                "duration_minutes": 300,
                "depart": "14:00",
                "arrive": "19:00",
                "provider": "United",
                "notes": "",
                "leg": {"origin": "FCA", "destination": "SFO"},
            },
        ]
        complete_rows.extend(award_pair_rows(award_rows, limit=5))

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "report.html"
            write_master_html(
                output,
                title="SFO to FCA Trip Search",
                cabin="economy",
                plan=plan,
                complete_rows=complete_rows,
                award_rows=award_rows,
                cash_one_way_rows=[],
                errors=[],
            )
            html = output.read_text(encoding="utf-8")

        self.assertIn("Best overall", html)
        self.assertIn("Complete Plans", html)
        self.assertIn("Outbound Award Options", html)
        self.assertIn("Return Award Options", html)
        self.assertIn("round-trip", html)
        self.assertIn("award pair", html)
        self.assertIn("Cash Details Verified", html)
        self.assertIn("10:15 -&gt; 13:20", html)
        self.assertNotIn('data-view-tab="plans"', html)
        self.assertNotIn('id="plansView"', html)

    def test_master_report_uses_valid_checkbox_filters_and_builder_detail_markers(self) -> None:
        plan = expand_trip_search(
            origins=["SFO", "SJC"],
            destinations=["FCA", "MSO"],
            outbound_dates=["2026-09-04", "2026-09-05"],
            return_dates=["2026-09-07"],
        )
        complete_rows = [
            {
                "kind": "cash",
                "route": "SFO -> FCA / FCA -> SFO",
                "dates": "2026-09-04 / 2026-09-07",
                "origin": "SFO",
                "destination": "FCA",
                "outbound_date": "2026-09-04",
                "return_origin": "FCA",
                "return_destination": "SFO",
                "return_date": "2026-09-07",
                "same_airports": True,
                "trip_type": "round-trip",
                "cash_detail_status": "complete",
                "cash_detail_source": "fli",
                "price": "$450.00",
                "effective": "$450.00",
                "effective_num": 450.0,
                "cpp": "",
                "cpp_num": 0.0,
                "award_points": 0.0,
                "award_components": [],
                "cash_component_usd": 450.0,
                "score": 520.0,
                "score_label": "520.00",
                "stops": "1 + 1",
                "stops_num": 2,
                "duration": "9h",
                "duration_minutes": 540,
                "depart": "09:00 / 10:15",
                "arrive": "15:00 / 13:20",
                "outbound_depart": "09:00",
                "outbound_arrive": "15:00",
                "return_depart": "10:15",
                "return_arrive": "13:20",
                "provider": "cash",
                "notes": "round trip cash fare",
                "outbound_cell": "SFO -> FCA\n2026-09-04\n09:00 -> 15:00\nUA 100 / UA 200, 2 stop(s), 4h 30m",
                "return_cell": "FCA -> SFO\n2026-09-07\n10:15 -> 13:20\nUA 201 / UA 101, 1 stop(s), 4h 30m",
                "outbound_leg_detail": {
                    "origin": "SFO",
                    "destination": "FCA",
                    "date": "2026-09-04",
                    "depart_time": "09:00",
                    "arrive_time": "15:00",
                    "flight_numbers": "UA 100 / UA 200",
                    "carriers": "UA",
                    "stops": 2,
                    "duration_display": "4h 30m",
                    "segments": [
                        {
                            "origin": "SFO",
                            "destination": "DEN",
                            "depart_time": "09:00",
                            "arrive_time": "11:30",
                            "airline": "UA",
                            "flight_number": "100",
                        }
                    ],
                    "layovers": [{"airport": "DEN", "duration_minutes": 60}],
                },
                "return_leg_detail": {
                    "origin": "FCA",
                    "destination": "SFO",
                    "date": "2026-09-07",
                    "depart_time": "10:15",
                    "arrive_time": "13:20",
                    "flight_numbers": "UA 201 / UA 101",
                    "carriers": "UA",
                    "stops": 1,
                    "duration_display": "4h 30m",
                    "segments": [],
                    "layovers": [],
                },
            },
            {
                "kind": "cash",
                "route": "SJC -> MSO / MSO -> SJC",
                "dates": "2026-09-05 / 2026-09-07",
                "origin": "SJC",
                "destination": "MSO",
                "outbound_date": "2026-09-05",
                "return_origin": "MSO",
                "return_destination": "SJC",
                "return_date": "2026-09-07",
                "same_airports": True,
                "trip_type": "round-trip",
                "cash_detail_status": "complete",
                "cash_detail_source": "fli",
                "price": "$500.00",
                "effective": "$500.00",
                "effective_num": 500.0,
                "cpp": "",
                "cpp_num": 0.0,
                "award_points": 0.0,
                "award_components": [],
                "cash_component_usd": 500.0,
                "score": 560.0,
                "score_label": "560.00",
                "stops": "0 + 0",
                "stops_num": 0,
                "duration": "7h",
                "duration_minutes": 420,
                "depart": "10:00 / 11:00",
                "arrive": "13:00 / 14:00",
                "outbound_depart": "10:00",
                "outbound_arrive": "13:00",
                "return_depart": "11:00",
                "return_arrive": "14:00",
                "provider": "cash",
                "notes": "",
                "outbound_cell": "SJC -> MSO\n2026-09-05\n10:00 -> 13:00\nDL 100, 0 stop(s), 3h",
                "return_cell": "MSO -> SJC\n2026-09-07\n11:00 -> 14:00\nDL 101, 0 stop(s), 4h",
                "outbound_leg_detail": {"origin": "SJC", "destination": "MSO", "stops": 0, "carriers": "DL"},
                "return_leg_detail": {"origin": "MSO", "destination": "SJC", "stops": 0, "carriers": "DL"},
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "report.html"
            write_master_html(
                output,
                title="SFO/SJC to FCA/MSO Trip Search",
                cabin="economy",
                plan=plan,
                complete_rows=complete_rows,
                award_rows=[],
                cash_one_way_rows=[],
                errors=[],
            )
            html = output.read_text(encoding="utf-8")

        self.assertNotIn("id=\"kindFilter\"", html)
        self.assertNotIn("id=\"tripFilter\"", html)
        self.assertNotIn("id=\"lateFilter\"", html)
        self.assertNotIn("Plan Type", html)
        self.assertNotIn("buildKindFilter", html)
        self.assertNotIn('data-view-tab="plans"', html)
        self.assertNotIn('id="plansView"', html)
        self.assertIn('id="planResultsTemplate"', html)
        self.assertIn("[hidden] {", html)
        self.assertIn("window.tripReportShowView", html)
        self.assertIn("button.dataset.viewBound", html)
        self.assertIn("planTemplate.content.cloneNode(true)", html)
        self.assertIn('planResults ? planResults.querySelectorAll(".trip-card") : []', html)
        self.assertIn('data-filter-key="origin" value="SFO"', html)
        self.assertIn('data-filter-key="origin" value="SJC"', html)
        self.assertNotIn('data-filter-key="origin" value="FCA"', html)
        self.assertIn('data-filter-key="destination" value="FCA"', html)
        self.assertIn('data-filter-key="destination" value="MSO"', html)
        self.assertNotIn('data-filter-key="destination" value="SFO"', html)
        self.assertNotIn('data-filter-key="returnDate"', html)
        self.assertIn("Max Stops Per Leg", html)
        self.assertRegex(html, r'data-outbound-stops="2(?:\.0)?"')
        self.assertRegex(html, r'data-return-stops="1(?:\.0)?"')
        self.assertIn('legStopValue(row, "outboundStops") <= maxStops', html)
        self.assertIn('legStopValue(row, "returnStops") <= maxStops', html)
        self.assertIn("data-compatible", html)
        self.assertIn("No match with selected", html)
        self.assertIn('id="outboundSort"', html)
        self.assertIn('id="returnSort"', html)
        self.assertIn('<option value="convenience">Convenience</option>', html)
        self.assertIn('sortChoiceGroups(bestByKey(pool, "outboundKey"), "outboundKey", outboundSort.value)', html)
        self.assertIn('sortChoiceGroups(bestByKey(pool, "returnKey"), "returnKey", returnSort.value)', html)
        self.assertIn('button.dataset.compatible === "false"', html)
        self.assertIn('selectedReturnKey = "";', html)
        self.assertIn('selectedOutboundKey = "";', html)
        self.assertIn("plan-card-head", html)
        self.assertIn("plan-metrics", html)
        self.assertIn("plan-timeline-list", html)
        self.assertIn("flight-timeline", html)
        self.assertIn("timeline-segment", html)
        self.assertIn("timeline-layover", html)
        self.assertIn("timeline-fallback", html)
        self.assertIn('renderLegTimeline("Outbound flight", outboundDetail)', html)
        self.assertIn('renderLegTimeline("Inbound flight", returnDetail)', html)
        self.assertNotIn("renderLegDetail", html)
        self.assertNotIn("segment-list", html)
        self.assertIn("choice-compact", html)
        self.assertIn("choice-logo-cell", html)
        self.assertIn("choice-facts", html)
        self.assertIn("choice-metric-strip", html)
        self.assertIn("choice-mini-metric", html)
        self.assertIn("Effective USD", html)
        self.assertIn("integerMoney(sampleCard.dataset.effective)", html)
        self.assertIn("legLogosHtml(detail)", html)
        self.assertIn("carrierLine(detail)", html)
        self.assertIn("layoverSummary(detail)", html)
        self.assertIn("carrierCodesFromDetail", html)
        self.assertIn("legPaymentIconHtml(detail", html)
        self.assertIn("legPairIconsHtml(outboundDetail, returnDetail)", html)
        self.assertIn("pointsLabel(detail.points)", html)
        self.assertIn("detail.taxes", html)
        self.assertIn("choice-switch", html)
        self.assertIn('Switches ${escapeHtml(switchLabel)}', html)
        self.assertIn('keyName === "returnKey" ? "outbound" : "inbound"', html)
        self.assertIn(".leg-choice .plan-icon", html)
        self.assertIn("airline-logo-config", html)

        self.assertEqual(leg_stop_value(complete_rows[0], "outbound"), 2)
        self.assertEqual(leg_stop_value(complete_rows[0], "return"), 1)

    def test_master_report_marks_missing_cash_return_timing(self) -> None:
        plan = expand_trip_search(
            origins=["SFO"],
            destinations=["MSO"],
            outbound_dates=["2026-09-04"],
            return_dates=["2026-09-07"],
        )
        complete_rows = [
            {
                "kind": "cash",
                "route": "SFO -> MSO / MSO -> SFO",
                "dates": "2026-09-04 / 2026-09-07",
                "origin": "SFO",
                "destination": "MSO",
                "outbound_date": "2026-09-04",
                "return_origin": "MSO",
                "return_destination": "SFO",
                "return_date": "2026-09-07",
                "same_airports": True,
                "trip_type": "round-trip",
                "cash_detail_status": "outbound_only",
                "cash_detail_source": "provider_parser",
                "price": "$289.00",
                "effective": "$289.00",
                "effective_num": 289.0,
                "score": 370.92,
                "score_label": "370.92",
                "stops": "1 + ?",
                "stops_num": 1,
                "duration": "6 hr 23 min",
                "duration_minutes": 383,
                "depart": "10:00",
                "arrive": "17:23",
                "outbound_depart": "10:00",
                "outbound_arrive": "17:23",
                "return_depart": "",
                "return_arrive": "",
                "provider": "cash",
                "notes": "round trip cash fare, return timing unavailable",
                "outbound_cell": "SFO -> MSO\n2026-09-04\n10:00 -> 17:23\nDelta, 1 stop(s), 6 hr 23 min",
                "return_cell": "MSO -> SFO\n2026-09-07\nTiming unavailable",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "report.html"
            write_master_html(
                output,
                title="SFO to MSO Trip Search",
                cabin="economy",
                plan=plan,
                complete_rows=complete_rows,
                award_rows=[],
                cash_one_way_rows=[],
                errors=[],
            )
            html = output.read_text(encoding="utf-8")

        self.assertIn("timing missing", html)
        self.assertIn("Timing unavailable", html)
        self.assertIn("Cash details: 0/1 priced fares have verified return timing", html)

    def test_recommendations_do_not_promote_unverified_cash_as_overall(self) -> None:
        cash_row = {
            "kind": "cash",
            "route": "SFO -> MSO / MSO -> SFO",
            "dates": "2026-09-04 / 2026-09-07",
            "trip_type": "round-trip",
            "same_airports": True,
            "cash_detail_status": "outbound_only",
            "price": "$289.00",
            "effective": "$289.00",
            "effective_num": 289.0,
            "score": 370.92,
            "score_label": "370.92",
            "stops_num": 1,
            "duration_minutes": 383,
            "depart": "10:00",
            "arrive": "17:23",
            "outbound_depart": "10:00",
            "return_depart": "",
            "notes": "return timing unavailable",
        }
        award_row = {
            "kind": "award pair",
            "route": "SFO -> MSO / MSO -> SFO",
            "dates": "2026-09-05 / 2026-09-07",
            "trip_type": "award pair",
            "same_airports": True,
            "price": "AC 15,000 + CAD 46.70 / AS 27,500 + $5.60",
            "effective": "$617.00",
            "effective_num": 617.0,
            "score": 855.08,
            "score_label": "855.08",
            "stops_num": 3,
            "duration_minutes": 889,
            "depart": "06:15 / 07:15",
            "arrive": "13:27 / 14:52",
            "outbound_depart": "06:15",
            "return_depart": "07:15",
            "notes": "book as two separate awards",
        }

        cards = recommendation_cards([cash_row, award_row])

        self.assertEqual(cards[0]["label"], "Best overall")
        self.assertEqual(cards[0]["row"]["kind"], "award pair")
        cash_cards = [card for card in cards if card["row"]["kind"] == "cash"]
        self.assertEqual(len(cash_cards), 1)
        self.assertIn("return unverified", cash_cards[0]["label"])
        self.assertNotIn("Cheapest tolerable", cash_cards[0]["label"])

    def test_master_report_calls_out_missing_cash(self) -> None:
        plan = expand_trip_search(
            origins=["SFO"],
            destinations=["DTW"],
            outbound_dates=["2026-11-13"],
            return_dates=["2026-11-29"],
        )
        award_pair = {
            "kind": "award pair",
            "route": "SFO -> DTW / DTW -> SFO",
            "dates": "2026-11-13 / 2026-11-29",
            "trip_type": "award pair",
            "price": "UA 15,000 + $5.60 / UA 15,000 + $5.60",
            "effective": "$371.20",
            "effective_num": 371.2,
            "score": 450.0,
            "score_label": "450.00",
            "stops": "0 + 0",
            "stops_num": 0,
            "duration": "9h",
            "duration_minutes": 540,
            "depart": "09:00 / 12:00",
            "arrive": "17:00 / 20:00",
            "provider": "United / United",
            "notes": "",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "report.html"
            write_master_html(
                output,
                title="SFO to DTW Trip Search",
                cabin="economy",
                plan=plan,
                complete_rows=[award_pair],
                award_rows=[],
                cash_one_way_rows=[],
                errors=["Cash provider returned no parseable fares"],
            )
            html = output.read_text(encoding="utf-8")

        self.assertIn("Cash unavailable", html)
        self.assertIn("1 cash itineraries checked", html)
        self.assertIn("No priced cash fares", html)

    def test_mixed_cash_award_and_cash_one_way_pairs_are_complete_plans(self) -> None:
        cash_rows = [
            {
                "kind": "outbound cash",
                "direction": "outbound",
                "route": "SFO -> DTW",
                "dates": "2026-11-13",
                "origin": "SFO",
                "destination": "DTW",
                "trip_type": "cash one-way",
                "price": "$180.00",
                "effective": "$180.00",
                "effective_num": 180.0,
                "score": 230.0,
                "score_label": "230.00",
                "stops": 0,
                "stops_num": 0,
                "duration": "4h 30m",
                "duration_minutes": 270,
                "depart": "09:00",
                "arrive": "16:30",
                "provider": "cash",
                "notes": "cash one-way fare",
                "outbound_detail": "SFO -> DTW 2026-11-13: 09:00 -> 16:30, DL 123, 0 stop(s), 4h 30m",
                "outbound_cell": "SFO -> DTW\n2026-11-13\n09:00 -> 16:30\nDL 123, 0 stop(s), 4h 30m",
                "leg": {"origin": "SFO", "destination": "DTW", "date": "2026-11-13"},
            },
            {
                "kind": "return cash",
                "direction": "return",
                "route": "DTW -> SFO",
                "dates": "2026-11-29",
                "origin": "DTW",
                "destination": "SFO",
                "trip_type": "cash one-way",
                "price": "$220.00",
                "effective": "$220.00",
                "effective_num": 220.0,
                "score": 280.0,
                "score_label": "280.00",
                "stops": 1,
                "stops_num": 1,
                "duration": "6h",
                "duration_minutes": 360,
                "depart": "12:00",
                "arrive": "15:00",
                "provider": "cash",
                "notes": "cash one-way fare",
                "return_detail": "DTW -> SFO 2026-11-29: 12:00 -> 15:00, UA 456, 1 stop(s), 6h",
                "return_cell": "DTW -> SFO\n2026-11-29\n12:00 -> 15:00\nUA 456, 1 stop(s), 6h",
                "leg": {"origin": "DTW", "destination": "SFO", "date": "2026-11-29"},
            },
        ]
        award_rows = [
            {
                "kind": "return award",
                "direction": "return",
                "route": "DTW -> SFO",
                "dates": "2026-11-29",
                "trip_type": "award one-way",
                "price": "UA 15,000 + $5.60",
                "effective": "$185.60",
                "effective_num": 185.60,
                "score": 250.0,
                "score_label": "250.00",
                "stops": 0,
                "stops_num": 0,
                "duration": "5h",
                "duration_minutes": 300,
                "depart": "14:00",
                "arrive": "17:00",
                "provider": "United",
                "notes": "",
                "outbound_detail": "DTW -> SFO 2026-11-29: 14:00 -> 17:00, UA 789, 0 stop(s), 5h",
                "return_cell": "DTW -> SFO\n2026-11-29\n14:00 -> 17:00\nUA 789, 0 stop(s), 5h",
                "leg": {"origin": "DTW", "destination": "SFO", "date": "2026-11-29"},
            }
        ]

        cash_pairs = cash_one_way_pair_rows(cash_rows, limit=10)
        mixed_pairs = mixed_cash_award_rows(cash_rows, award_rows, limit=10)

        self.assertEqual(cash_pairs[0]["kind"], "cash one-ways")
        self.assertEqual(cash_pairs[0]["effective_num"], 400.0)
        self.assertIn("compare against real round-trip/open-jaw cash fare", cash_pairs[0]["notes"])
        self.assertEqual(mixed_pairs[0]["kind"], "cash + award")
        self.assertEqual(mixed_pairs[0]["price"], "Cash $180.00 / UA 15,000 + $5.60")
        self.assertIn("book cash outbound and award return separately", mixed_pairs[0]["notes"])

    def test_same_price_two_one_ways_are_suggested_for_flexibility(self) -> None:
        true_cash = {
            "kind": "cash",
            "route": "SFO -> DTW / DTW -> SFO",
            "dates": "2026-11-14 / 2026-11-30",
            "origin": "SFO",
            "destination": "DTW",
            "outbound_date": "2026-11-14",
            "return_origin": "DTW",
            "return_destination": "SFO",
            "return_date": "2026-11-30",
            "same_airports": True,
            "trip_type": "round-trip",
            "price": "$359.00",
            "effective": "$359.00",
            "effective_num": 359.0,
            "score": 383.58,
            "score_label": "383.58",
            "stops": "0 + 1",
            "stops_num": 1,
            "duration": "14h 22m",
            "duration_minutes": 862,
            "depart": "12:45 / 19:30",
            "arrive": "20:40 / 01:57 +1",
            "outbound_depart": "12:45",
            "return_depart": "19:30",
            "notes": "round trip cash fare",
        }
        two_one_ways = {
            **true_cash,
            "kind": "cash one-ways",
            "trip_type": "two one-ways",
            "price": "$209.00 / $150.00",
            "score": 450.0,
            "score_label": "450.00",
            "notes": "book as two separate paid one-way tickets",
        }

        cash_rows, one_way_rows = annotate_cash_strategy_comparisons([true_cash], [two_one_ways])
        cards = recommendation_cards([*cash_rows, *one_way_rows])
        best_cash_cards = [card for card in cards if "Suggested cash: two one-ways" in card["label"]]

        self.assertEqual(len(best_cash_cards), 1)
        self.assertEqual(best_cash_cards[0]["row"]["kind"], "cash one-ways")
        self.assertTrue(best_cash_cards[0]["row"]["cash_flex_recommended"])
        self.assertIn("same price as true two-leg fare; more flexible", best_cash_cards[0]["row"]["notes"])
        self.assertIn("two one-ways are same price and more flexible", cash_rows[0]["notes"])


if __name__ == "__main__":
    unittest.main()
