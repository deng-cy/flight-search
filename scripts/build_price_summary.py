from __future__ import annotations

import argparse
from html import escape
import sys
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from flight_search_common.formatting import money, normalize_airport, points, slug
from flight_search_common.io import load_json, markdown_escape
from flight_search_common.web_awards import load_web_award_rows

DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "reports"
AIRLINE_CODES = {
    "Air Canada": "AC",
    "Alaska": "AS",
    "American": "AA",
    "Delta": "DL",
    "Frontier": "F9",
    "Southwest": "WN",
    "United": "UA",
}
AWARD_PROGRAM_CODES = {
    "aeroplan": "AC",
    "alaska": "AS",
    "american": "AA",
    "azul": "AD",
    "delta": "DL",
    "flyingblue": "AF",
    "southwest": "WN",
    "united": "UA",
    "velocity": "VA",
    "virginatlantic": "VS",
}


def default_paths(origin: str, destination: str, departure_date: str, cabin: str) -> dict[str, Path]:
    route_stem = f"{slug(origin)}_{slug(destination)}_{departure_date}"
    cash_stem = f"{route_stem}_{cabin.replace('-', '_')}"
    return {
        "cash_json": WORKSPACE_ROOT / "cash" / "data" / "normalized" / f"{cash_stem}_cash_fares.json",
        "award_json": WORKSPACE_ROOT / "seat_aero" / "data" / f"{route_stem}_best_flights.json",
        "award_full_json": WORKSPACE_ROOT / "seat_aero" / "data" / f"{route_stem}_normalized_full.json",
        "output": DEFAULT_OUTPUT_DIR / f"{cash_stem}_cash_award_summary.md",
        "html_output": DEFAULT_OUTPUT_DIR / f"{cash_stem}_cash_award_summary.html",
    }


def numeric(value: Any, default: float = 10**12) -> float:
    if value in (None, ""):
        return default
    return float(value)


def top_cash_rows(rows: list[dict[str, Any]], cabin: str, limit: int) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if row.get("bookable") is True
        and row.get("cabin") == cabin
        and row.get("cash_price_usd") != ""
    ]
    return sorted(
        candidates,
        key=lambda row: (
            numeric(row.get("score")),
            numeric(row.get("cash_price_usd")),
            numeric(row.get("duration_minutes")),
            numeric(row.get("provider_rank")),
        ),
    )[:limit]


def top_award_rows(rows: list[dict[str, Any]], cabin: str, limit: int) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if row.get("bookable") is True
        and row.get("comparable") is True
        and row.get("cabin") == cabin
        and row.get("effective_usd") != ""
    ]
    return sorted(
        candidates,
        key=lambda row: (
            numeric(row.get("score")),
            numeric(row.get("effective_usd")),
            numeric(row.get("duration_minutes")),
        ),
    )[:limit]


def carrier_codes(value: Any) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    if text in AIRLINE_CODES:
        return {AIRLINE_CODES[text]}
    return {part.strip() for part in text.split(",") if part.strip()}


def normalized_stops(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def award_match_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    index: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    candidates = [
        row
        for row in rows
        if row.get("flight_numbers")
        and row.get("bookable") is True
        and row.get("comparable") is True
    ]
    for row in sorted(candidates, key=lambda item: (numeric(item.get("score")), numeric(item.get("effective_usd")))):
        stops = normalized_stops(row.get("stops"))
        if stops is None:
            continue
        for code in carrier_codes(row.get("carriers")):
            key = (str(row.get("depart_time", "")), str(row.get("arrive_time", "")), stops, code)
            index.setdefault(key, row)
    return index


def enrich_cash_flight_numbers(
    cash_rows: list[dict[str, Any]],
    award_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index = award_match_index(award_rows)
    enriched = []
    for row in cash_rows:
        copy = dict(row)
        stops = normalized_stops(copy.get("stops"))
        matched = None
        if stops is not None:
            for code in carrier_codes(copy.get("carriers")):
                key = (str(copy.get("depart_time", "")), str(copy.get("arrive_time", "")), stops, code)
                matched = index.get(key)
                if matched:
                    break
        if matched:
            copy["matched_award_flight_numbers"] = matched["flight_numbers"]
        enriched.append(copy)
    return enriched


def cash_flight_label(row: dict[str, Any]) -> str:
    return row.get("flight_numbers") or row.get("matched_award_flight_numbers") or row.get("carriers", "")


def cash_price(row: dict[str, Any]) -> str:
    return compact_money(row.get("cash_price_usd"), "USD")


def award_price(row: dict[str, Any]) -> str:
    program_code = award_program_code(row)
    prefix = f"{program_code} " if program_code else ""
    return f"{prefix}{points(row.get('mileage_cost'))} + {compact_money(row.get('taxes_amount'), row.get('taxes_currency') or 'USD')}"


def compact_money(amount: Any, currency: str = "USD") -> str:
    if amount in (None, ""):
        return ""
    value = float(amount)
    if currency == "USD":
        return f"${value:,.2f}"
    return f"{currency} {value:,.2f}"


def award_program_code(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "").strip().lower()
    if source in AWARD_PROGRAM_CODES:
        return AWARD_PROGRAM_CODES[source]

    program = str(row.get("program") or "").lower()
    if "flying blue" in program or "air france" in program:
        return "AF"
    if "alaska" in program:
        return "AS"
    if "delta" in program:
        return "DL"
    if "southwest" in program or "rapid rewards" in program:
        return "WN"
    if "united" in program:
        return "UA"
    if "virgin" in program:
        return "VS"
    if "aeroplan" in program or "air canada" in program:
        return "AC"
    return source.upper()


def score(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):.2f}"


def duration(value: Any) -> str:
    if value in (None, ""):
        return ""
    minutes = int(value)
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def table_row(values: list[Any]) -> str:
    return "| " + " | ".join(markdown_escape(value) for value in values) + " |"


def combined_rows(
    *,
    cash_rows: list[dict[str, Any]],
    award_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, row in enumerate(cash_rows, start=1):
        rows.append(
            {
                "type": "cash",
                "rank": rank,
                "depart": row.get("depart_time", ""),
                "arrive": row.get("arrive_time", ""),
                "flight": cash_flight_label(row),
                "provider": "cash",
                "stops": row.get("stops", ""),
                "duration": row.get("duration_display", ""),
                "duration_minutes": numeric(row.get("duration_minutes"), 0),
                "price": cash_price(row),
                "effective": money(row.get("effective_usd"), "USD"),
                "effective_num": numeric(row.get("effective_usd")),
                "score": score(row.get("score")),
                "score_num": numeric(row.get("score")),
                "notes": row.get("flags", ""),
            }
        )

    for rank, row in enumerate(award_rows, start=1):
        rows.append(
            {
                "type": "award",
                "rank": rank,
                "depart": row.get("depart_time", ""),
                "arrive": row.get("arrive_time", ""),
                "flight": row.get("flight_numbers", ""),
                "provider": row.get("program", ""),
                "stops": row.get("stops", ""),
                "duration": duration(row.get("duration_minutes")),
                "duration_minutes": numeric(row.get("duration_minutes"), 0),
                "price": award_price(row),
                "effective": money(row.get("effective_usd"), "USD"),
                "effective_num": numeric(row.get("effective_usd")),
                "score": score(row.get("score")),
                "score_num": numeric(row.get("score")),
                "notes": row.get("flags", ""),
            }
        )
    return rows


def write_summary(
    path: Path,
    *,
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str,
    cash_path: Path,
    award_path: Path,
    award_web_paths: list[Path],
    cash_rows: list[dict[str, Any]],
    award_rows: list[dict[str, Any]],
) -> None:
    award_sources = [str(award_path), *[str(path) for path in award_web_paths]]
    lines = [
        f"# {normalize_airport(origin)} to {normalize_airport(destination)} Cash and Award Summary on {departure_date}",
        "",
        f"- Cabin: `{cabin}`",
        f"- Cash source: `{cash_path}`",
        f"- Award source(s): `{'; '.join(award_sources)}`",
        "",
        "Cash rows are observed comparable paid fares. Award rows use configured point valuations to compute effective USD.",
        "",
        "Score starts with effective USD, then adds penalties for stops, duration, next-day arrival, and inconvenient departure/arrival times. Award rows can receive a small remaining-seat credit.",
        "",
        "| Type | Rank | Depart | Arrive | Flight or Carrier | Stops | Duration | Price | Effective USD | Score | Notes |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]

    rows = combined_rows(cash_rows=cash_rows, award_rows=award_rows)
    if not rows:
        lines.append(table_row(["-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "No rows found"]))

    for row in rows:
        lines.append(
            table_row(
                [
                    row["type"],
                    row["rank"],
                    row["depart"],
                    row["arrive"],
                    row["flight"],
                    row["stops"],
                    row["duration"],
                    row["price"],
                    row["effective"],
                    row["score"],
                    row["notes"],
                ]
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def unique_values(rows: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(row.get(key, "")) for row in rows if row.get(key, "")})


def option_tags(values: list[str]) -> str:
    return "\n".join(f'<option value="{escape(value)}">{escape(value)}</option>' for value in values)


def stat_value(rows: list[dict[str, Any]], row_type: str, key: str) -> float | None:
    values = [row[key] for row in rows if row["type"] == row_type and row[key] < 10**12]
    return min(values) if values else None


def write_html_summary(
    path: Path,
    *,
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str,
    rows: list[dict[str, Any]],
) -> None:
    best_cash = stat_value(rows, "cash", "effective_num")
    best_award = stat_value(rows, "award", "effective_num")
    best_cash_score = stat_value(rows, "cash", "score_num")
    best_award_score = stat_value(rows, "award", "score_num")
    providers = unique_values(rows, "provider")
    stop_values = unique_values(rows, "stops")

    row_tags = []
    for row in rows:
        row_tags.append(
            "<tr "
            f'data-type="{escape(row["type"])}" '
            f'data-provider="{escape(str(row["provider"]))}" '
            f'data-stops="{escape(str(row["stops"]))}" '
            f'data-score="{row["score_num"]}" '
            f'data-effective="{row["effective_num"]}" '
            f'data-duration="{row["duration_minutes"]}">'
            f'<td><span class="pill {escape(row["type"])}">{escape(row["type"])}</span></td>'
            f'<td data-sort="{row["rank"]}">{row["rank"]}</td>'
            f'<td>{escape(str(row["depart"]))}</td>'
            f'<td>{escape(str(row["arrive"]))}</td>'
            f'<td class="strong">{escape(str(row["flight"]))}</td>'
            f'<td data-sort="{escape(str(row["stops"]))}">{escape(str(row["stops"]))}</td>'
            f'<td data-sort="{row["duration_minutes"]}">{escape(str(row["duration"]))}</td>'
            f'<td>{escape(str(row["price"]))}</td>'
            f'<td data-sort="{row["effective_num"]}">{escape(str(row["effective"]))}</td>'
            f'<td data-sort="{row["score_num"]}">{escape(str(row["score"]))}</td>'
            f'<td class="notes">{escape(str(row["notes"]))}</td>'
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(normalize_airport(origin))} to {escape(normalize_airport(destination))} Flight Summary</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #16202a;
      --muted: #687684;
      --line: #d9e1e8;
      --surface: #ffffff;
      --soft: #f5f7fa;
      --cash: #0f766e;
      --award: #6d4cc2;
      --accent: #235d8f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #eef3f6;
      letter-spacing: 0;
    }}
    header {{
      padding: 28px 32px 18px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }}
    .eyebrow {{
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      line-height: 1.2;
      font-weight: 760;
    }}
    main {{ padding: 22px 32px 34px; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .stat {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .stat span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .stat strong {{
      display: block;
      margin-top: 5px;
      font-size: 22px;
      line-height: 1.2;
    }}
    .score-guide {{
      margin: 0 0 18px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
      color: #334252;
      font-size: 14px;
      line-height: 1.45;
    }}
    .score-guide strong {{
      display: inline-block;
      margin-right: 6px;
      color: var(--ink);
    }}
    .controls {{
      display: grid;
      grid-template-columns: minmax(220px, 2fr) repeat(4, minmax(130px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }}
    label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    input, select {{
      min-height: 38px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: var(--surface);
      color: var(--ink);
      font: inherit;
    }}
    .table-wrap {{
      overflow: auto;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      min-width: 1040px;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
      font-size: 14px;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8fafc;
      color: #334252;
      font-size: 12px;
      text-transform: uppercase;
      cursor: pointer;
    }}
    tbody tr:hover {{ background: var(--soft); }}
    td:nth-child(2), td:nth-child(6), td:nth-child(7), td:nth-child(9), td:nth-child(10) {{
      text-align: right;
    }}
    .strong {{ font-weight: 740; }}
    .notes {{
      color: var(--muted);
      white-space: normal;
      min-width: 220px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-width: 54px;
      justify-content: center;
      border-radius: 999px;
      padding: 3px 8px;
      color: #fff;
      font-size: 12px;
      font-weight: 760;
      text-transform: uppercase;
    }}
    .pill.cash {{ background: var(--cash); }}
    .pill.award {{ background: var(--award); }}
    .count {{
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      .stats, .controls {{ grid-template-columns: 1fr 1fr; }}
      h1 {{ font-size: 24px; }}
    }}
    @media (max-width: 620px) {{
      .stats, .controls {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <p class="eyebrow">{escape(cabin)} cabin · {escape(departure_date)}</p>
    <h1>{escape(normalize_airport(origin))} to {escape(normalize_airport(destination))} Cash and Award Summary</h1>
  </header>
  <main>
    <section class="stats" aria-label="Summary">
      <div class="stat"><span>Best Cash</span><strong>{escape(money(best_cash, "USD") if best_cash is not None else "")}</strong></div>
      <div class="stat"><span>Best Award Effective</span><strong>{escape(money(best_award, "USD") if best_award is not None else "")}</strong></div>
      <div class="stat"><span>Best Cash Score</span><strong>{escape(score(best_cash_score))}</strong></div>
      <div class="stat"><span>Best Award Score</span><strong>{escape(score(best_award_score))}</strong></div>
    </section>
    <section class="score-guide" aria-label="Score explanation">
      <strong>Score:</strong> lower is better. It starts with effective USD, then adds penalties for stops, travel duration, next-day arrival, and inconvenient departure or arrival times. Award rows can also receive a small credit for more remaining seats.
    </section>
    <section class="controls" aria-label="Filters">
      <label>Search<input id="search" type="search" placeholder="Flight, carrier, program code"></label>
      <label>Type<select id="typeFilter"><option value="">All</option><option value="cash">Cash</option><option value="award">Award</option></select></label>
      <label>Program<select id="providerFilter"><option value="">All</option>{option_tags(providers)}</select></label>
      <label>Stops<select id="stopsFilter"><option value="">All</option>{option_tags(stop_values)}</select></label>
      <label>Max Score<input id="scoreFilter" type="number" min="0" step="1" placeholder="Any"></label>
    </section>
    <p class="count"><span id="visibleCount">0</span> of {len(rows)} rows</p>
    <div class="table-wrap">
      <table id="results">
        <thead>
          <tr>
            <th data-key="type">Type</th>
            <th data-key="rank">Rank</th>
            <th data-key="depart">Depart</th>
            <th data-key="arrive">Arrive</th>
            <th data-key="flight">Flight or Carrier</th>
            <th data-key="stops">Stops</th>
            <th data-key="duration">Duration</th>
            <th data-key="price">Price</th>
            <th data-key="effective">Effective USD</th>
            <th data-key="score">Score</th>
            <th data-key="notes">Notes</th>
          </tr>
        </thead>
        <tbody>
          {"".join(row_tags)}
        </tbody>
      </table>
    </div>
  </main>
  <script>
    const table = document.querySelector("#results");
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const controls = {{
      search: document.querySelector("#search"),
      type: document.querySelector("#typeFilter"),
      provider: document.querySelector("#providerFilter"),
      stops: document.querySelector("#stopsFilter"),
      score: document.querySelector("#scoreFilter"),
      visibleCount: document.querySelector("#visibleCount")
    }};
    let sortState = {{ index: 9, direction: "asc" }};

    function text(row) {{ return (row.innerText + " " + row.dataset.provider).toLowerCase(); }}
    function sortValue(row, index) {{
      const cell = row.children[index];
      const raw = cell.dataset.sort ?? cell.innerText;
      const numeric = Number(raw);
      return Number.isNaN(numeric) ? raw.toLowerCase() : numeric;
    }}
    function applyFilters() {{
      const query = controls.search.value.trim().toLowerCase();
      const maxScore = controls.score.value === "" ? Infinity : Number(controls.score.value);
      let visible = 0;
      rows.forEach(row => {{
        const keep =
          (!query || text(row).includes(query)) &&
          (!controls.type.value || row.dataset.type === controls.type.value) &&
          (!controls.provider.value || row.dataset.provider === controls.provider.value) &&
          (!controls.stops.value || row.dataset.stops === controls.stops.value) &&
          (Number(row.dataset.score) <= maxScore);
        row.hidden = !keep;
        if (keep) visible += 1;
      }});
      controls.visibleCount.textContent = visible;
    }}
    function applySort(index, direction) {{
      rows.sort((a, b) => {{
        const av = sortValue(a, index);
        const bv = sortValue(b, index);
        if (av < bv) return direction === "asc" ? -1 : 1;
        if (av > bv) return direction === "asc" ? 1 : -1;
        return 0;
      }});
      rows.forEach(row => tbody.appendChild(row));
      applyFilters();
    }}
    table.querySelectorAll("th").forEach((th, index) => {{
      th.addEventListener("click", () => {{
        const direction = sortState.index === index && sortState.direction === "asc" ? "desc" : "asc";
        sortState = {{ index, direction }};
        applySort(index, direction);
      }});
    }});
    Object.values(controls).forEach(control => {{
      if (control instanceof HTMLInputElement || control instanceof HTMLSelectElement) {{
        control.addEventListener("input", applyFilters);
        control.addEventListener("change", applyFilters);
      }}
    }});
    applySort(sortState.index, sortState.direction);
  </script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a combined cash and award price summary table.")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--cabin", default="economy")
    parser.add_argument("--cash-json")
    parser.add_argument("--award-json")
    parser.add_argument("--award-full-json")
    parser.add_argument("--award-web-json", action="append", default=[], help="Additional normalized award_web JSON file.")
    parser.add_argument("--no-award-web", action="store_true", help="Do not auto-include matching cached award_web rows.")
    parser.add_argument("--output")
    parser.add_argument("--html-output")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--html-limit", type=int, default=0, help="Rows per type in HTML. 0 includes all available rows.")
    args = parser.parse_args()

    paths = default_paths(args.origin, args.destination, args.date, args.cabin)
    cash_path = Path(args.cash_json) if args.cash_json else paths["cash_json"]
    award_path = Path(args.award_json) if args.award_json else paths["award_json"]
    award_full_path = Path(args.award_full_json) if args.award_full_json else paths["award_full_json"]
    output_path = Path(args.output) if args.output else paths["output"]
    html_output_path = Path(args.html_output) if args.html_output else paths["html_output"]
    explicit_award_web_paths = [Path(path) for path in args.award_web_json]
    web_award_rows = [] if args.no_award_web else load_web_award_rows(
        WORKSPACE_ROOT,
        origin=args.origin,
        destination=args.destination,
        departure_date=args.date,
        cabin=args.cabin,
        paths=explicit_award_web_paths or None,
    )
    auto_award_web_paths = [] if args.no_award_web or explicit_award_web_paths else [
        path
        for path in (WORKSPACE_ROOT / "award_web" / "data" / "normalized").glob(
            f"*_{slug(args.origin)}_{slug(args.destination)}_{args.date}_{args.cabin.replace('-', '_')}_one_way_web_awards.json"
        )
    ]
    award_web_paths = explicit_award_web_paths or sorted(auto_award_web_paths)

    award_rows = top_award_rows([*load_json(award_path), *web_award_rows], args.cabin, args.limit)
    award_match_rows = [*load_json(award_full_path if award_full_path.exists() else award_path), *web_award_rows]
    cash_rows = enrich_cash_flight_numbers(
        top_cash_rows(load_json(cash_path), args.cabin, args.limit),
        award_match_rows,
    )
    html_limit = args.html_limit if args.html_limit > 0 else 10**9
    html_award_rows = top_award_rows([*load_json(award_path), *web_award_rows], args.cabin, html_limit)
    html_cash_rows = enrich_cash_flight_numbers(
        top_cash_rows(load_json(cash_path), args.cabin, html_limit),
        award_match_rows,
    )
    write_summary(
        output_path,
        origin=args.origin,
        destination=args.destination,
        departure_date=args.date,
        cabin=args.cabin,
        cash_path=cash_path,
        award_path=award_path,
        award_web_paths=award_web_paths,
        cash_rows=cash_rows,
        award_rows=award_rows,
    )
    write_html_summary(
        html_output_path,
        origin=args.origin,
        destination=args.destination,
        departure_date=args.date,
        cabin=args.cabin,
        rows=combined_rows(cash_rows=html_cash_rows, award_rows=html_award_rows),
    )
    print(f"Wrote {len(cash_rows)} cash rows and {len(award_rows)} award rows to {output_path}")
    print(f"Wrote {len(html_cash_rows)} cash rows and {len(html_award_rows)} award rows to {html_output_path}")


if __name__ == "__main__":
    main()
