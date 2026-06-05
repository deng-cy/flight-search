from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from flight_search_common.io import load_json, markdown_escape, write_csv, write_json

from .models import CASH_FIELDNAMES, CashSearchRequest
from .normalization import normalize_cash_payload
from .providers.fli_provider import search_fli


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PREFERENCES_PATH = WORKSPACE_ROOT / "config/search_preferences.yaml"


def load_preferences(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        preferences = yaml.safe_load(handle)
    if not isinstance(preferences, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return preferences


def output_paths(output_dir: Path, request: CashSearchRequest) -> dict[str, Path]:
    return {
        "raw": output_dir / "raw" / f"{request.stem}_fli_raw.json",
        "normalized_json": output_dir / "normalized" / f"{request.stem}_cash_fares.json",
        "normalized_csv": output_dir / "normalized" / f"{request.stem}_cash_fares.csv",
        "report_md": output_dir / "reports" / f"{request.stem}_cash_fares.md",
    }


def infer_trip_type(
    *,
    origin: str,
    destination: str,
    return_date: str | None,
    return_origin: str | None,
    return_destination: str | None,
    requested_trip_type: str,
) -> tuple[str, str | None, str | None]:
    if not return_date:
        if requested_trip_type not in {"auto", "one-way"}:
            return requested_trip_type, return_origin, return_destination
        return "one-way", None, None

    normalized_origin = origin.strip().upper()
    normalized_destination = destination.strip().upper()
    normalized_return_origin = (return_origin or destination).strip().upper()
    normalized_return_destination = (return_destination or origin).strip().upper()

    if requested_trip_type != "auto":
        return requested_trip_type, normalized_return_origin, normalized_return_destination
    if normalized_return_origin == normalized_destination and normalized_return_destination == normalized_origin:
        return "round-trip", normalized_return_origin, normalized_return_destination
    return "multi-city", normalized_return_origin, normalized_return_destination


def ensure_raw_response(
    request: CashSearchRequest,
    raw_path: Path,
    *,
    refresh: bool,
) -> dict[str, Any]:
    if raw_path.exists() and not refresh:
        return load_json(raw_path)

    payload = search_fli(request)
    write_json(raw_path, payload)
    return payload


def write_report(
    path: Path,
    rows: list[dict[str, Any]],
    request: CashSearchRequest,
    *,
    limit: int = 50,
) -> None:
    lines = [
        f"# {request.origin} to {request.destination} Cash Fares on {request.departure_date}",
        "",
        f"- Trip type: `{request.trip_type}`",
        f"- Cabin: `{request.cabin}`",
        f"- Adults: `{request.adults}`",
        f"- Currency requested: `{request.currency}`",
        f"- Provider: `fli`",
        "",
    ]
    if request.trip_type != "one-way":
        lines.insert(
            3,
            f"- Return leg: `{request.return_origin} -> {request.return_destination}` on `{request.return_date}`",
        )

    visible_rows = rows[:limit]
    if len(rows) > len(visible_rows):
        lines.append(f"_Showing first {len(visible_rows)} of {len(rows)} normalized fares._")
        lines.append("")

    lines.extend(
        [
            "| Rank | Outbound | Return | Carrier | Cabin | Stops | Price | Duration | Detail | Score | Confidence | Flags |",
            "|---:|---|---|---|---|---:|---:|---:|---|---:|---:|---|",
        ]
    )

    if not rows:
        lines.extend(["", "No cash fares were normalized from the provider response."])
    else:
        for rank, row in enumerate(visible_rows, start=1):
            price = row["cash_price_usd"]
            if price != "":
                price_display = f"USD {float(price):,.2f}"
            elif row["cash_price_amount"] != "":
                price_display = f"{row['cash_price_currency']} {float(row['cash_price_amount']):,.2f}"
            else:
                price_display = row["raw_price"] or ""

            outbound_display = (
                f"{row.get('outbound_origin', request.origin)} -> "
                f"{row.get('outbound_destination', request.destination)} "
                f"{row.get('outbound_date', request.departure_date)} "
                f"{row.get('outbound_depart_time', row.get('depart_time', ''))} -> "
                f"{row.get('outbound_arrive_time', row.get('arrive_time', ''))}"
            )
            if request.trip_type == "one-way":
                return_display = ""
            elif row.get("return_depart_time") or row.get("return_arrive_time"):
                return_display = (
                    f"{row.get('return_origin', request.return_origin)} -> "
                    f"{row.get('return_destination', request.return_destination)} "
                    f"{row.get('return_date', request.return_date)} "
                    f"{row.get('return_depart_time', '')} -> {row.get('return_arrive_time', '')}"
                )
            else:
                return_display = (
                    f"{row.get('return_origin', request.return_origin)} -> "
                    f"{row.get('return_destination', request.return_destination)} "
                    f"{row.get('return_date', request.return_date)} timing unavailable"
                )

            lines.append(
                "| "
                + " | ".join(
                    markdown_escape(value)
                    for value in [
                        rank,
                        outbound_display,
                        return_display,
                        row["carriers"],
                        row["cabin"],
                        row["stops"],
                        price_display,
                        row["duration_display"],
                        row.get("cash_detail_status", ""),
                        row["score"],
                        row["confidence"],
                        row["flags"],
                    ]
                )
                + " |"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def run_pipeline(
    *,
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str = "economy",
    adults: int = 1,
    currency: str = "USD",
    fetch_mode: str = "fallback",
    max_stops: int | None = None,
    trip_type: str = "one-way",
    return_date: str | None = None,
    return_origin: str | None = None,
    return_destination: str | None = None,
    output_dir: Path = DEFAULT_DATA_DIR,
    preferences_path: Path = DEFAULT_PREFERENCES_PATH,
    refresh: bool = False,
) -> dict[str, Any]:
    resolved_trip_type, resolved_return_origin, resolved_return_destination = infer_trip_type(
        origin=origin,
        destination=destination,
        return_date=return_date,
        return_origin=return_origin,
        return_destination=return_destination,
        requested_trip_type=trip_type,
    )
    request = CashSearchRequest(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        cabin=cabin,
        adults=adults,
        currency=currency,
        fetch_mode=fetch_mode,
        max_stops=max_stops,
        trip_type=resolved_trip_type,
        return_date=return_date,
        return_origin=resolved_return_origin,
        return_destination=resolved_return_destination,
    )
    paths = output_paths(output_dir, request)
    raw_payload = ensure_raw_response(request, paths["raw"], refresh=refresh)
    preferences = load_preferences(preferences_path)
    rows = normalize_cash_payload(raw_payload, request, paths["raw"], preferences)

    write_json(paths["normalized_json"], rows)
    write_csv(paths["normalized_csv"], rows, CASH_FIELDNAMES)
    write_report(paths["report_md"], rows, request)

    summary = {
        "raw_response": str(paths["raw"]),
        "normalized_count": len(rows),
        "outputs": {
            "normalized_json": str(paths["normalized_json"]),
            "normalized_csv": str(paths["normalized_csv"]),
            "report_md": str(paths["report_md"]),
        },
        "preferences": str(preferences_path),
    }
    if raw_payload.get("provider_error"):
        summary["provider_error"] = raw_payload["provider_error"]
    return summary
