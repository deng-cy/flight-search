from __future__ import annotations

import unittest
from pathlib import Path

from flight_search_common.provider_catalog import load_provider_catalog


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class ProviderCatalogTests(unittest.TestCase):
    def test_catalog_maps_airline_and_program_aliases(self) -> None:
        catalog = load_provider_catalog(WORKSPACE_ROOT / "config" / "provider_catalog.yaml")

        self.assertEqual(catalog.airline_code("Delta"), "DL")
        self.assertEqual(catalog.airline_code("Air Canada"), "AC")
        self.assertEqual(catalog.airline_code("Air France/KLM Flying Blue / cash"), "AF")
        self.assertEqual(catalog.airline_code("cash"), "")
        self.assertEqual(catalog.award_program_code("Rapid Rewards"), "WN")
        self.assertEqual(catalog.award_program_code("Air France/KLM Flying Blue"), "AF")
        self.assertEqual(catalog.airline_logo_files()["UA"], WORKSPACE_ROOT / "assets" / "united.png")
        self.assertEqual(catalog.airline_logo_files()["WN"], WORKSPACE_ROOT / "assets" / "southwest.jpeg")

    def test_catalog_exposes_award_web_capabilities(self) -> None:
        catalog = load_provider_catalog(WORKSPACE_ROOT / "config" / "provider_catalog.yaml")

        self.assertIn("delta", catalog.award_web_provider_keys())
        self.assertIn("southwest", catalog.award_web_provider_keys())
        self.assertIn("southwest", catalog.one_way_only_round_trip_sources())
        self.assertNotIn("delta", catalog.one_way_only_round_trip_sources())
        self.assertEqual(catalog.award_web_label("delta"), "Delta Web")


if __name__ == "__main__":
    unittest.main()
