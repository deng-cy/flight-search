from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from flight_search_common.formatting import arrival_label, money, points as miles, source_from_path, time_label
from flight_search_common.io import load_json, write_csv

DEFAULT_VALUATIONS = PROJECT_ROOT / "data/point_values.json"


def value_config(source: str, valuations: dict[str, Any]) -> tuple[str, float, bool]:
    programs = valuations.get("programs", {})
    default_cpp = float(valuations.get("default_cents_per_point", 2.0))
    config = programs.get(source)
    if not config:
        return source, default_cpp, True
    return config.get("label", source), float(config["cents_per_point"]), False


def cash_equivalent_display(points_value_usd: float, taxes_amount: float, taxes_currency: str) -> str:
    if taxes_currency == "USD":
        return money(points_value_usd + taxes_amount)
    return f"{money(points_value_usd)} + {money(taxes_amount, taxes_currency)} tax"


def collect_rows(trip_details_dir: Path, valuations: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for path in sorted(trip_details_dir.glob("*.json")):
        source = source_from_path(path)
        program_label, cpp, used_default = value_config(source, valuations)
        payload = load_json(path)

        for trip in payload.get("data", []):
            mileage_cost = int(trip.get("MileageCost") or 0)
            taxes_raw = int(trip.get("TotalTaxes") or 0)
            taxes_amount = taxes_raw / 100
            taxes_currency = trip.get("TaxesCurrency") or "USD"
            points_value_usd = mileage_cost * cpp / 100
            total_usd = points_value_usd + taxes_amount if taxes_currency == "USD" else None

            rows.append(
                {
                    "source": source,
                    "program": program_label,
                    "used_default_cpp": used_default,
                    "cents_per_point": cpp,
                    "flight_numbers": trip.get("FlightNumbers", ""),
                    "cabin": trip.get("Cabin", ""),
                    "stops": trip.get("Stops", ""),
                    "connections": ", ".join(trip.get("Connections") or []),
                    "carriers": trip.get("Carriers", ""),
                    "remaining_seats": trip.get("RemainingSeats", ""),
                    "departs_at_raw": trip.get("DepartsAt", ""),
                    "arrives_at_raw": trip.get("ArrivesAt", ""),
                    "depart_time": time_label(trip.get("DepartsAt")),
                    "arrive_time": arrival_label(trip.get("DepartsAt"), trip.get("ArrivesAt")),
                    "mileage_cost": mileage_cost,
                    "taxes_amount": taxes_amount,
                    "taxes_currency": taxes_currency,
                    "points_value_usd": round(points_value_usd, 2),
                    "total_equivalent_usd_when_tax_usd": round(total_usd, 2) if total_usd is not None else "",
                    "cash_equivalent_display": cash_equivalent_display(points_value_usd, taxes_amount, taxes_currency),
                    "aircraft": ", ".join(trip.get("Aircraft") or []),
                }
            )

    return sorted(
        rows,
        key=lambda row: (
            row["departs_at_raw"],
            row["flight_numbers"],
            row["cabin"],
            row["source"],
            row["mileage_cost"],
        ),
    )


def cash_value_fieldnames() -> list[str]:
    fieldnames = [
        "source",
        "program",
        "used_default_cpp",
        "cents_per_point",
        "flight_numbers",
        "cabin",
        "stops",
        "connections",
        "carriers",
        "remaining_seats",
        "depart_time",
        "arrive_time",
        "mileage_cost",
        "taxes_amount",
        "taxes_currency",
        "points_value_usd",
        "total_equivalent_usd_when_tax_usd",
        "cash_equivalent_display",
        "aircraft",
        "departs_at_raw",
        "arrives_at_raw",
    ]
    return fieldnames


def write_markdown(path: Path, rows: list[dict[str, Any]], valuations: dict[str, Any], title: str) -> None:
    default_cpp = valuations.get("default_cents_per_point", 2.0)
    default_sources = sorted({row["source"] for row in rows if row["used_default_cpp"]})

    lines = [
        f"# {title}",
        "",
        "## Point Values",
        "",
        f"- Default for missing programs: {default_cpp} cents/point",
    ]

    for source, config in sorted(valuations.get("programs", {}).items()):
        lines.append(f"- {config.get('label', source)} (`{source}`): {config['cents_per_point']} cents/point")

    if default_sources:
        lines.extend(
            [
                "",
                "Programs using the default value: " + ", ".join(f"`{source}`" for source in default_sources),
            ]
        )

    lines.extend(
        [
            "",
            "Taxes are shown in the currency returned by Seats.aero. The points component is valued in USD.",
            "",
            "## Flights",
            "",
            "| Depart | Arrive | Flights | Program | Cabin | Stops | Seats | Price | Point value | Cash equivalent |",
            "|---:|---:|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )

    for row in rows:
        price = f"{miles(row['mileage_cost'])} + {money(row['taxes_amount'], row['taxes_currency'])}"
        point_value = money(row["points_value_usd"])
        default_mark = " *" if row["used_default_cpp"] else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    row["depart_time"],
                    row["arrive_time"],
                    row["flight_numbers"],
                    row["program"] + default_mark,
                    row["cabin"],
                    str(row["stops"]),
                    str(row["remaining_seats"]),
                    price,
                    point_value,
                    row["cash_equivalent_display"],
                ]
            )
            + " |"
        )

    if default_sources:
        lines.extend(["", "`*` Program used the default 2.0 cents/point value."])

    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cash-equivalent award flight tables from saved Seats.aero trip details.")
    parser.add_argument("--trip-details-dir", required=True)
    parser.add_argument("--valuations", default=str(DEFAULT_VALUATIONS))
    parser.add_argument("--markdown-output", required=True)
    parser.add_argument("--csv-output", required=True)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()

    valuations = load_json(Path(args.valuations))
    rows = collect_rows(Path(args.trip_details_dir), valuations)
    write_csv(Path(args.csv_output), rows, cash_value_fieldnames())
    write_markdown(Path(args.markdown_output), rows, valuations, args.title)
    print(f"Wrote {len(rows)} rows to {args.markdown_output}")
    print(f"Wrote {len(rows)} rows to {args.csv_output}")


if __name__ == "__main__":
    main()
