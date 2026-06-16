from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from award_web.delta.pipeline import DEFAULT_DATA_DIR, DEFAULT_PREFERENCES_PATH, run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and normalize no-login Delta web award observations.")
    parser.add_argument("--origin", required=True, help="Origin IATA airport code, e.g. SFO.")
    parser.add_argument("--destination", required=True, help="Destination IATA airport code, e.g. DTW.")
    parser.add_argument("--date", required=True, help="Departure date in YYYY-MM-DD format.")
    parser.add_argument("--trip-type", default="one-way", choices=["one-way", "round-trip"])
    parser.add_argument("--return-date", help="Return date in YYYY-MM-DD format for round-trip searches.")
    parser.add_argument("--return-origin", help="Return leg origin. Defaults to outbound destination for round trips.")
    parser.add_argument("--return-destination", help="Return leg destination. Defaults to outbound origin for round trips.")
    parser.add_argument(
        "--cabin",
        default="economy",
        choices=["economy", "premium-economy", "business", "first"],
    )
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--output-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--preferences", default=str(DEFAULT_PREFERENCES_PATH))
    parser.add_argument("--refresh", action="store_true", help="Fetch a fresh Delta page instead of reusing cached evidence.")
    parser.add_argument("--headed", action="store_true", help="Show the browser while Playwright runs.")
    parser.add_argument("--flexible-dates", action="store_true", help="Leave Delta's flexible date option enabled.")
    parser.add_argument("--timeout-ms", type=int, default=45000)
    args = parser.parse_args()

    summary = run_pipeline(
        origin=args.origin,
        destination=args.destination,
        departure_date=args.date,
        cabin=args.cabin,
        adults=args.adults,
        trip_type=args.trip_type,
        return_date=args.return_date,
        return_origin=args.return_origin,
        return_destination=args.return_destination,
        output_dir=Path(args.output_dir),
        preferences_path=Path(args.preferences),
        refresh=args.refresh,
        headless=not args.headed,
        flexible_dates=args.flexible_dates,
        timeout_ms=args.timeout_ms,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
