from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from flight_search_common.formatting import slug
from flight_search_common.io import write_json

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"


def fetch_json(url: str) -> Any:
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def summarize_search(search_payload: dict[str, Any], trip_details: dict[str, Any]) -> dict[str, Any]:
    rows = []
    sources = set()
    route_ids = set()
    carrier_codes = set()
    booking_labels = set()

    for item in search_payload.get("data", []):
        source = item.get("Source") or item.get("Route", {}).get("Source")
        route = item.get("Route", {})
        availability_id = item.get("ID")
        sources.add(source)
        route_ids.add(item.get("RouteID"))

        for key, value in item.items():
            if key.endswith("Airlines") and isinstance(value, str):
                for carrier in value.split(","):
                    carrier = carrier.strip()
                    if carrier:
                        carrier_codes.add(carrier)

        detail = trip_details.get(availability_id) or {}
        for label in detail.get("booking_links", []):
            if label.get("label"):
                booking_labels.add(label["label"])
        for carrier in detail.get("carriers", {}).keys():
            carrier_codes.add(carrier)

        trips = item.get("AvailabilityTrips") or []
        for trip in trips:
            for carrier in str(trip.get("Carriers", "")).split(","):
                carrier = carrier.strip()
                if carrier:
                    carrier_codes.add(carrier)

        rows.append(
            {
                "availability_id": availability_id,
                "source": source,
                "origin": route.get("OriginAirport"),
                "destination": route.get("DestinationAirport"),
                "date": item.get("Date"),
                "economy_available": item.get("YAvailable"),
                "premium_available": item.get("WAvailable"),
                "business_available": item.get("JAvailable"),
                "first_available": item.get("FAvailable"),
                "economy_miles": item.get("YMileageCostRaw"),
                "business_miles": item.get("JMileageCostRaw"),
                "taxes_currency": item.get("TaxesCurrency"),
                "economy_taxes": item.get("YTotalTaxesRaw"),
                "business_taxes": item.get("JTotalTaxesRaw"),
                "direct_economy_available": item.get("YDirect"),
                "direct_business_available": item.get("JDirect"),
                "trip_count": len(trips),
            }
        )

    return {
        "count": search_payload.get("count"),
        "has_more": search_payload.get("hasMore"),
        "cursor": search_payload.get("cursor"),
        "sources_found": sorted(s for s in sources if s),
        "route_ids_found": sorted(r for r in route_ids if r),
        "carrier_codes_seen": sorted(carrier_codes),
        "booking_labels_seen": sorted(booking_labels),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Save raw Seats.aero search data from the local FastAPI wrapper.")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--include-trip-details", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{slug(args.origin)}_{slug(args.destination)}_{args.date}"
    query = urlencode(
        {
            "origin_airport": args.origin,
            "destination_airport": args.destination,
            "start_date": args.date,
            "end_date": args.date,
            "take": 1000,
            "include_trips": "true",
            "minify_trips": "true",
        }
    )
    search_url = f"{args.base_url.rstrip('/')}/search?{query}"
    search_payload = fetch_json(search_url)

    raw_search_path = output_dir / f"{stem}_search_raw.json"
    write_json(raw_search_path, search_payload)

    trip_details: dict[str, Any] = {}
    if args.include_trip_details:
        trip_dir = output_dir / f"{stem}_trip_details"
        trip_dir.mkdir(parents=True, exist_ok=True)

        for item in search_payload.get("data", []):
            availability_id = item["ID"]
            source = item.get("Source", "unknown")
            detail_url = f"{args.base_url.rstrip('/')}/trips/{availability_id}"
            detail_payload = fetch_json(detail_url)
            trip_details[availability_id] = detail_payload
            detail_path = trip_dir / f"{source}_{availability_id}.json"
            write_json(detail_path, detail_payload)

    summary = summarize_search(search_payload, trip_details)
    summary_path = output_dir / f"{stem}_summary.json"
    write_json(summary_path, summary)

    print(f"Saved raw search: {raw_search_path}")
    if args.include_trip_details:
        print(f"Saved trip details: {output_dir / f'{stem}_trip_details'}")
    print(f"Saved summary: {summary_path}")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
