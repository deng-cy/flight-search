from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ROOT.parent
for path in (WORKSPACE_ROOT, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.find_best_flights import (
    apply_dynamic_price_flags,
    best_deduped_rows,
    build_full_rows,
    configured_time_penalty,
    convert_to_usd,
    load_fx_rates,
    load_preferences,
    program_value,
)


PREFERENCES = WORKSPACE_ROOT / "config/search_preferences.yaml"
SFO_DTW_DETAILS = ROOT / "data/sfo_dtw_2026-10-14_trip_details"


class FindBestFlightsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preferences = load_preferences(PREFERENCES)
        self.fx_rates = {
            "USD": 1.0,
            "CAD": 1.35,
            "AUD": 1.50,
            "BRL": 5.0,
        }

    def test_yaml_loading_and_default_program_value(self) -> None:
        label, cpp, used_default = program_value("delta", self.preferences)
        self.assertEqual(label, "Delta SkyMiles")
        self.assertEqual(cpp, 1.2)
        self.assertFalse(used_default)

        label, cpp, used_default = program_value("american", self.preferences)
        self.assertEqual(label, "american")
        self.assertEqual(cpp, 2.0)
        self.assertTrue(used_default)

    def test_cached_fx_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            snapshot = {
                "amount": 1.0,
                "base": "USD",
                "date": "2026-05-20",
                "rates": {"CAD": 1.25, "BRL": 5.0},
            }
            (cache_dir / "2026-05-20_USD.json").write_text(json.dumps(snapshot))
            preferences = dict(self.preferences)
            preferences["currency"] = dict(self.preferences["currency"])
            preferences["currency"]["cache_dir"] = str(cache_dir)

            rates, source = load_fx_rates(preferences, offline_fx=True)

        self.assertEqual(source, "cache:2026-05-20")
        self.assertEqual(rates["USD"], 1.0)
        converted, ok = convert_to_usd(12.5, "CAD", rates)
        self.assertTrue(ok)
        self.assertEqual(converted, 10.0)

    def test_time_penalty_windows(self) -> None:
        rules = self.preferences["ranking"]["time_penalties"]

        penalty, labels = configured_time_penalty("2026-10-14T06:00:00Z", rules["departure"])
        self.assertEqual(penalty, 50)
        self.assertEqual(labels, ["early departure"])

        penalty, labels = configured_time_penalty("2026-10-14T22:45:00Z", rules["departure"])
        self.assertEqual(penalty, 75)
        self.assertEqual(labels, ["late departure"])

        penalty, labels = configured_time_penalty("2026-10-15T00:03:00Z", rules["arrival"])
        self.assertEqual(penalty, 100)
        self.assertEqual(labels, ["after-midnight arrival"])

    def test_sfo_dtw_fixture_keeps_dl717_priced_sources(self) -> None:
        rows = build_full_rows(SFO_DTW_DETAILS, self.preferences, self.fx_rates, "test")
        apply_dynamic_price_flags(rows, self.preferences)

        dl717 = [
            row
            for row in rows
            if row["flight_numbers"] == "DL717"
            and row["cabin"] == "economy"
            and row["stops"] == 0
        ]
        sources = {row["source"] for row in dl717}
        self.assertEqual(sources, {"delta", "flyingblue", "virginatlantic"})

        by_source = {row["source"]: row for row in dl717}
        self.assertEqual(by_source["flyingblue"]["effective_usd"], 196.44)
        self.assertLess(by_source["flyingblue"]["effective_usd"], by_source["virginatlantic"]["effective_usd"])
        self.assertLess(by_source["virginatlantic"]["effective_usd"], by_source["delta"]["effective_usd"])

        best_rows = best_deduped_rows(rows, 40)
        best_dl717 = [
            row
            for row in best_rows
            if row["flight_numbers"] == "DL717"
            and row["cabin"] == "economy"
            and row["stops"] == 0
        ]
        self.assertEqual(len(best_dl717), 1)
        self.assertEqual(best_dl717[0]["source"], "flyingblue")
        self.assertIn("Virgin Atlantic Flying Club", best_dl717[0]["alternates"])
        self.assertIn("Delta SkyMiles", best_dl717[0]["alternates"])

    def test_zero_seat_rows_stay_full_but_not_best_bookable(self) -> None:
        rows = build_full_rows(SFO_DTW_DETAILS, self.preferences, self.fx_rates, "test")
        apply_dynamic_price_flags(rows, self.preferences)

        zero_seat_rows = [row for row in rows if row["remaining_seats"] == 0]
        self.assertTrue(zero_seat_rows)
        self.assertTrue(all(not row["bookable"] for row in zero_seat_rows))

        best_rows = best_deduped_rows(rows, 0)
        self.assertTrue(best_rows)
        self.assertTrue(all(row["remaining_seats"] >= 1 for row in best_rows))


if __name__ == "__main__":
    unittest.main()
