from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flight_search_common.preferences import deep_merge, load_preferences


class PreferencesTests(unittest.TestCase):
    def test_deep_merge_preserves_base_values_and_replaces_lists(self) -> None:
        merged = deep_merge(
            {
                "points": {
                    "default_cents_per_point": 2.0,
                    "programs": {"delta": {"label": "Delta", "cents_per_point": 1.2}},
                },
                "ranking": {"time_penalties": {"departure": [{"label": "early", "penalty_usd": 50}]}},
            },
            {
                "points": {"programs": {"delta": {"cents_per_point": 1.4}}},
                "ranking": {"time_penalties": {"departure": [{"label": "early", "penalty_usd": 25}]}},
            },
        )

        self.assertEqual(merged["points"]["default_cents_per_point"], 2.0)
        self.assertEqual(merged["points"]["programs"]["delta"]["label"], "Delta")
        self.assertEqual(merged["points"]["programs"]["delta"]["cents_per_point"], 1.4)
        self.assertEqual(merged["ranking"]["time_penalties"]["departure"][0]["penalty_usd"], 25)

    def test_load_preferences_applies_local_overlay_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferences = root / "search_preferences.yaml"
            preferences.write_text(
                """
points:
  default_cents_per_point: 2.0
  programs:
    delta:
      label: Delta SkyMiles
      cents_per_point: 1.2
ranking:
  duration_penalty_usd_per_hour: 5
""".strip()
                + "\n",
                encoding="utf-8",
            )
            (root / "search_preferences.local.yaml").write_text(
                """
points:
  programs:
    delta:
      cents_per_point: 1.5
ranking:
  duration_penalty_usd_per_hour: 8
""".strip()
                + "\n",
                encoding="utf-8",
            )

            default_only = load_preferences(preferences)
            with_overlay = load_preferences(preferences, apply_local_overlay=True)

        self.assertEqual(default_only["points"]["programs"]["delta"]["cents_per_point"], 1.2)
        self.assertEqual(with_overlay["points"]["programs"]["delta"]["label"], "Delta SkyMiles")
        self.assertEqual(with_overlay["points"]["programs"]["delta"]["cents_per_point"], 1.5)
        self.assertEqual(with_overlay["ranking"]["duration_penalty_usd_per_hour"], 8)
