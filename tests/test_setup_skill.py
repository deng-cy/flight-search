from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = WORKSPACE_ROOT / ".codex/skills/setup/scripts/setup_repo.py"


def load_setup_module():
    spec = importlib.util.spec_from_file_location("setup_repo", SETUP_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load setup script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup_repo = load_setup_module()


class SetupSkillScriptTests(unittest.TestCase):
    def test_temp_setup_writes_env_without_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "seat_aero").mkdir()
            (root / "seat_aero/.env.example").write_text(
                "SEATS_AERO_API_KEY=pro_xxxxxxxxxxxxxxxxxxxxx\n"
                "SEATS_AERO_BASE_URL=https://seats.aero\n"
                "SEATS_AERO_REQUEST_TIMEOUT_SECONDS=30\n"
                "SEATS_AERO_ENABLE_LIVE_SEARCH=false\n",
                encoding="utf-8",
            )
            (root / "config").mkdir()
            (root / "config/search_preferences.yaml").write_text(
                "points:\n"
                "  default_cents_per_point: 2.0\n"
                "  programs:\n"
                "    delta:\n"
                "      label: Delta SkyMiles\n"
                "      cents_per_point: 1.2\n"
                "ranking:\n"
                "  duration_penalty_usd_per_hour: 5\n"
                "  time_penalties:\n"
                "    departure: []\n"
                "    arrival: []\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SETUP_SCRIPT),
                    "--repo-root",
                    str(root),
                    "--api-key",
                    "pro_test_key",
                    "--use-default-preferences",
                    "--skip-dependencies",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            env_text = (root / "seat_aero/.env").read_text(encoding="utf-8")
            self.assertIn("SEATS_AERO_API_KEY=pro_test_key", env_text)
            self.assertIn("SEATS_AERO_BASE_URL=https://seats.aero", env_text)
            self.assertFalse((root / "config/search_preferences.local.yaml").exists())

    def test_store_override_removes_values_matching_tracked_defaults(self) -> None:
        base = {
            "points": {
                "programs": {"delta": {"label": "Delta SkyMiles", "cents_per_point": 1.2}},
            }
        }
        local = {"points": {"programs": {"delta": {"cents_per_point": 1.5}}}}

        setup_repo.store_override(local, base, ["points", "programs", "delta", "cents_per_point"], 1.2)

        self.assertEqual(local, {})
