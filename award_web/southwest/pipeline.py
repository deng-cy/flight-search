from __future__ import annotations

from pathlib import Path
from typing import Any

from flight_search_common.io import load_json, markdown_escape, write_csv, write_json
from flight_search_common.preferences import DEFAULT_PREFERENCES_PATH, load_preferences

from ..models import AWARD_WEB_FIELDNAMES, AwardWebSearchRequest
from .normalization import normalize_southwest_payload
from .provider import search_southwest_public


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def output_paths(output_dir: Path, request: AwardWebSearchRequest) -> dict[str, Path]:
    raw_dir = output_dir / "raw" / request.source_name / request.stem
    return {
        "raw_json": raw_dir / f"{request.stem}_raw.json",
        "html": raw_dir / f"{request.stem}.html",
        "screenshot": raw_dir / f"{request.stem}.png",
        "normalized_json": output_dir / "normalized" / f"{request.stem}_web_awards.json",
        "normalized_csv": output_dir / "normalized" / f"{request.stem}_web_awards.csv",
        "report_md": output_dir / "reports" / f"{request.stem}_web_awards.md",
    }


def ensure_raw_response(
    request: AwardWebSearchRequest,
    paths: dict[str, Path],
    *,
    refresh: bool,
    headless: bool,
    timeout_ms: int,
) -> dict[str, Any]:
    if paths["raw_json"].exists() and not refresh:
        return load_json(paths["raw_json"])

    payload = search_southwest_public(
        request,
        html_path=paths["html"],
        screenshot_path=paths["screenshot"],
        headless=headless,
        timeout_ms=timeout_ms,
    )
    write_json(paths["raw_json"], payload)
    return payload


def write_report(path: Path, rows: list[dict[str, Any]], request: AwardWebSearchRequest, payload: dict[str, Any]) -> None:
    status_message = " ".join(str(payload.get("status_message", "")).split())[:240]
    lines = [
        f"# Southwest Web Award Check: {request.origin} to {request.destination}",
        "",
        "- Trip type: `one-way`",
        f"- Departure date: `{request.departure_date}`",
        f"- Cabin: `{request.cabin}`",
        f"- Adults: `{request.adults}`",
        f"- Status: `{payload.get('status', '')}`",
        f"- Status message: {status_message}",
        f"- Evidence HTML: `{payload.get('evidence', {}).get('html', '')}`",
        f"- Evidence screenshot: `{payload.get('evidence', {}).get('screenshot', '')}`",
        "",
        "Southwest award trips are priced as one-way observations. Return-trip reports should sum separate outbound and return rows.",
        "",
        "| Rank | Flight | Depart | Arrive | Cabin | Stops | Points | Taxes | Effective | Score | Confidence | Flags |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    if not rows:
        lines.extend(["", "No Southwest web award rows were normalized from the captured page."])
    else:
        for rank, row in enumerate(rows, start=1):
            lines.append(
                "| "
                + " | ".join(
                    markdown_escape(value)
                    for value in [
                        rank,
                        row["flight_numbers"],
                        row["depart_time"],
                        row["arrive_time"],
                        row["cabin"],
                        row["stops"],
                        row["points"],
                        row["taxes_usd"],
                        row["effective_usd"],
                        row["score"],
                        row["confidence"],
                        row["flags"],
                    ]
                )
                + " |"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(
    *,
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str = "economy",
    adults: int = 1,
    trip_type: str = "one-way",
    return_date: str | None = None,
    return_origin: str | None = None,
    return_destination: str | None = None,
    output_dir: Path = DEFAULT_DATA_DIR,
    preferences_path: Path = DEFAULT_PREFERENCES_PATH,
    refresh: bool = False,
    headless: bool = True,
    timeout_ms: int = 45000,
) -> dict[str, Any]:
    if trip_type != "one-way" or return_date or return_origin or return_destination:
        raise ValueError("Southwest award web searches must be one-way searches; combine outbound and return rows in reports.")

    request = AwardWebSearchRequest(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        cabin=cabin,
        adults=adults,
        trip_type="one-way",
        source_name="southwest",
    )
    paths = output_paths(output_dir, request)
    used_live_fetch = refresh or not paths["raw_json"].exists()
    payload = ensure_raw_response(
        request,
        paths,
        refresh=refresh,
        headless=headless,
        timeout_ms=timeout_ms,
    )
    preferences = load_preferences(preferences_path)
    evidence_path = Path(payload.get("evidence", {}).get("screenshot") or payload.get("evidence", {}).get("html") or paths["raw_json"])
    rows = normalize_southwest_payload(payload, request, evidence_path, preferences)

    write_json(paths["normalized_json"], rows)
    write_csv(paths["normalized_csv"], rows, AWARD_WEB_FIELDNAMES)
    write_report(paths["report_md"], rows, request, payload)

    return {
        "provider": "southwest",
        "live": used_live_fetch,
        "status": payload.get("status", ""),
        "status_message": payload.get("status_message", ""),
        "normalized_count": len(rows),
        "raw_response": str(paths["raw_json"]),
        "outputs": {
            "normalized_json": str(paths["normalized_json"]),
            "normalized_csv": str(paths["normalized_csv"]),
            "report_md": str(paths["report_md"]),
            "html": str(paths["html"]),
            "screenshot": str(paths["screenshot"]),
        },
        "preferences": str(preferences_path),
    }
