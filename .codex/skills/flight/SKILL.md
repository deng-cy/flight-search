---
name: flight
description: Execute this Flight_search project's procedure for live or cached route/date flight searches. Use when Codex needs to search flights, refresh Seats.aero award data, refresh cash fares, compare cash and awards, start or verify the local Seats.aero API wrapper, regenerate markdown/HTML reports, or summarize flight options from this workspace.
---

# Flight

## Purpose

Use this skill to run the flight-search workflow for this project. Do not use it for routine code cleanup or architecture editing; those instructions belong in the workspace `AGENTS.md` files.

## Workspace

Work from `/Users/dengcy/Library/Mobile Documents/com~apple~CloudDocs/Agent/Flight_search`.

Core outputs:
- Award results: `seat_aero/data/{origin}_{destination}_{date}_best_flights.*`
- Cash results: `cash/data/normalized/{origin}_{destination}_{date}_{cabin}_cash_fares.*`
- Combined report: `reports/{origin}_{destination}_{date}_{cabin}_cash_award_summary.html`
- Multi-airport trip report: `reports/{origins}_to_{destinations}_out_{dates}_return_{dates}_{cabin}_trip_summary.html`
- Shared scoring config: `config/search_preferences.yaml`

Saved traveler defaults:
- Home airports: `SFO`, `SJC`
- Default cabin: `economy`

## Procedure

1. Normalize inputs:
   - Uppercase origin and destination.
   - Use `YYYY-MM-DD`.
   - Default cabin to `economy` unless the user specifies another cabin.

2. Start or verify the local Seats.aero wrapper for live award refreshes:
   - Check `http://127.0.0.1:8001/health` first when a server may already be running.
   - If needed, start from `seat_aero/`:
     ```bash
     ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
     ```
   - Use port `8001` if `8000` is unavailable. The API UI is `/docs`; the root URL is not useful.
   - The wrapper reads the real Seats.aero key from `seat_aero/.env`.

3. Refresh award data when the user asks for live results or the cache may be stale:
   ```bash
   .venv/bin/python seat_aero/scripts/find_best_flights.py \
     --origin SFO \
     --destination DTW \
     --date 2026-10-14 \
     --base-url http://127.0.0.1:8001 \
     --refresh
   ```
   Use `--offline-fx` only when live FX/network access is unavailable or the user asks for cached/offline output.

4. Refresh cash data:
   - The cash provider uses `flights`/`fli`, which requires Python `>=3.10`.
   ```bash
   .venv/bin/python cash/scripts/search_cash_fares.py \
     --origin SFO \
     --destination DTW \
     --date 2026-10-14 \
     --cabin economy \
     --currency USD \
     --refresh
   ```
   If the user does not require live cash refresh, omit `--refresh` to reuse the cached provider response.
   Use `FLI_TOP_N=1` for quick smoke checks, or raise it when cash completeness matters more than speed. The provider default is `3`.

   For two-leg paid itineraries, search the actual round-trip or open-jaw fare instead of adding two one-way cash prices:
   ```bash
   .venv/bin/python cash/scripts/search_cash_fares.py \
     --origin SFO \
     --destination FCA \
     --date 2026-09-04 \
     --return-origin FCA \
     --return-destination SFO \
     --return-date 2026-09-07 \
     --trip-type auto \
     --cabin economy \
     --currency USD \
     --refresh
   ```
   `--trip-type auto` uses `round-trip` for exact reverse returns and `multi-city` for open-jaw returns.

5. Build the combined report:
   ```bash
   .venv/bin/python scripts/build_price_summary.py \
     --origin SFO \
     --destination DTW \
     --date 2026-10-14 \
     --cabin economy
   ```

   For multi-airport, multi-day, return-trip searches, use the root trip orchestrator:
   ```bash
   .venv/bin/python scripts/run_trip_search.py \
     --origins SFO,SJC \
     --destinations FCA,MSO \
     --outbound-dates 2026-09-04,2026-09-05 \
     --return-dates 2026-09-07 \
     --cabin economy \
     --base-url http://127.0.0.1:8001 \
     --award-workers 4 \
     --cash-workers 3 \
     --refresh
   ```
   This expands every origin/destination/date combination for award legs and one-way cash legs, plus every outbound-return pairing for real paid cash itinerary pricing.
   The master report can show:
   - `cash`: actual round-trip or open-jaw paid fares.
   - `cash + award`: a one-way paid fare combined with a one-way award.
   - `cash one-ways`: two separately priced one-way paid tickets for comparison and, when same-price or cheaper, recommendation.
   - `award pair`: two one-way awards.
   Use `--award-workers 1 --cash-workers 1` when debugging provider behavior. Cached runs are usually too fast for worker counts to matter. In a live DTW-SFO/SFO-DTW 4-job sweep, `--award-workers 4` and `--cash-workers 4` were fastest; use `--award-workers 4 --cash-workers 3` as a stable default for live grids, raise cash to `4` when speed matters, and reduce cash workers if `fli` becomes flaky.

   For Delta award-web round trips, standalone Playwright can be blocked by Delta's edge bot checks even when the user's real Chrome session works. In that case, use the Chrome/browser tool to capture the visible Delta outbound and return pages into a JSON payload with `snapshots` entries for `stage: "outbound"` and `stage: "return"`, each containing `url`, `body_text`, and optionally `html_content`. Then normalize that capture through the Delta CLI:
   ```bash
   .venv/bin/python award_web/scripts/search_delta_awards.py \
     --origin SFO \
     --destination DTW \
     --date 2026-11-13 \
     --trip-type round-trip \
     --return-origin DTW \
     --return-destination SFO \
     --return-date 2026-11-29 \
     --cabin economy \
     --browser-capture-json /path/to/delta_browser_capture.json
   ```
   This writes the standard raw, normalized, and markdown outputs. Regenerate the master trip report afterward so parsed `legs.return` timing replaces stale "return selection not parsed" rows.

6. Verify outputs:
   - Confirm the script summaries show nonzero counts.
   - Open the HTML report through the local static server when visual verification is useful:
     ```bash
     .venv/bin/python -m http.server 8002 --bind 127.0.0.1
     ```
   - Visit `http://127.0.0.1:8002/reports/...html`.
   - Check that filters and sorting work for at least one type filter and one sorted numeric column.

## Interpretation Rules

- Cash rows are paid fare observations. Keep provider details visible in raw outputs, and show a data-quality warning if any provider result lacks timing or flight numbers.
- `fli` usually exposes structured outbound/return timing and flight numbers for paid fares. For selected two-leg cash tuples, use the final segment price as the complete itinerary price.
- When a return date is present, always search actual `round-trip` or `multi-city` provider pricing and one-way cash pricing. Compare them in the master report. If two one-ways are cheaper or the same price as the exact same-trip two-leg fare, prefer the two one-ways because they are more flexible.
- One-way cash searches are still required for mixed cash+award strategies and for a two-one-way cash comparison. Show those rows separately from actual two-leg paid fares.
- Cash rows may include `legs.outbound`, `legs.return`, `cash_detail_status`, and `cash_detail_source`. `complete` means both cash legs have timing details; `outbound_only` means the fare was priced as a two-leg itinerary but the provider only exposed outbound timing; `price_only` means the fare price exists without usable leg timing.
- The combined report may infer cash flight numbers by matching award rows on carrier, depart time, arrive time, and stop count.
- Award rows use Seats.aero trip details, so they usually have flight numbers.
- Award searches remain one-way by leg; the master report may pair outbound and return award legs as suggested complete award plans.
- `score` is a comparison score, not a fare. Lower is better.
- Score starts with effective USD and adds penalties from `config/search_preferences.yaml` for stops, duration, next-day arrival, and inconvenient times. Award rows can receive a small remaining-seat credit.
- Keep raw and normalized outputs even when expensive, unbookable, or low confidence.
- Treat Seats.aero timestamps as displayed local wall-clock strings despite a trailing `Z`.

## Final Response

Report:
- Whether live or cached data was used.
- Counts for cash rows, full award rows, and ranked award rows.
- The HTML report path/link.
- The best cash option and best award option by score.
- For multi-search reports, include the best overall complete plan and call out whether cash is round-trip or open-jaw.
- If mixed plans are present, include whether the cash leg is outbound or return and compare it against the best true two-leg cash fare.
- Any important limitations, such as unmatched cash flight numbers or a provider/network failure.
