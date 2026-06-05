from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


CASH_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = CASH_ROOT.parent
for path in (WORKSPACE_ROOT, CASH_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cash_search.pipeline import DEFAULT_DATA_DIR, DEFAULT_PREFERENCES_PATH, run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and normalize paid cash fares.")
    parser.add_argument("--origin", required=True, help="Origin IATA airport code, e.g. SFO.")
    parser.add_argument("--destination", required=True, help="Destination IATA airport code, e.g. DTW.")
    parser.add_argument("--date", required=True, help="Departure date in YYYY-MM-DD format.")
    parser.add_argument(
        "--trip-type",
        default="auto",
        choices=["auto", "one-way", "round-trip", "multi-city"],
        help="Paid-ticket trip type. auto infers round-trip or multi-city when return fields are present.",
    )
    parser.add_argument("--return-date", help="Return date in YYYY-MM-DD format for two-leg paid searches.")
    parser.add_argument("--return-origin", help="Return leg origin. Defaults to outbound destination when --return-date is set.")
    parser.add_argument("--return-destination", help="Return leg destination. Defaults to outbound origin when --return-date is set.")
    parser.add_argument(
        "--cabin",
        default="economy",
        choices=["economy", "premium-economy", "business", "first"],
    )
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--currency", default="USD")
    parser.add_argument(
        "--fetch-mode",
        default="fallback",
        choices=["common", "fallback", "force-fallback", "local"],
        help="Reserved provider mode option kept for CLI compatibility.",
    )
    parser.add_argument("--max-stops", type=int, default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--preferences", default=str(DEFAULT_PREFERENCES_PATH))
    parser.add_argument("--refresh", action="store_true", help="Fetch a fresh provider response.")
    args = parser.parse_args()

    summary = run_pipeline(
        origin=args.origin,
        destination=args.destination,
        departure_date=args.date,
        cabin=args.cabin,
        adults=args.adults,
        currency=args.currency,
        fetch_mode=args.fetch_mode,
        max_stops=args.max_stops,
        trip_type=args.trip_type,
        return_date=args.return_date,
        return_origin=args.return_origin,
        return_destination=args.return_destination,
        output_dir=Path(args.output_dir),
        preferences_path=Path(args.preferences),
        refresh=args.refresh,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
