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

from flight_search_common.io import write_json

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data/routes"


def fetch_json(url: str) -> Any:
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Save raw Seats.aero route-list data by mileage-program source.")
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {}
    for source in args.sources:
        query = urlencode({"source": source})
        payload = fetch_json(f"{args.base_url.rstrip('/')}/routes?{query}")
        path = output_dir / f"{source}_routes_raw.json"
        write_json(path, payload)

        routes = payload.get("data") if isinstance(payload, dict) else payload
        summary[source] = {
            "raw_file": str(path),
            "route_count": len(routes) if isinstance(routes, list) else None,
            "first_route": routes[0] if isinstance(routes, list) and routes else None,
        }

    summary_path = output_dir / "routes_summary.json"
    write_json(summary_path, summary)
    print(f"Saved route summary: {summary_path}")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
