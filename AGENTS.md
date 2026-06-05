# Flight Search Architecture

This workspace is organized as a three-stage flight search pipeline. Keep the root focused on orchestration notes, shared conventions, and cross-module architecture. Module-specific code and data should live inside the module folder that owns it.

## Folder Roles

- `seat_aero/`: Seats.aero API wrapper, raw award data capture, award normalization, point valuation, FX conversion, and best-award ranking. Its detailed operating notes live in `seat_aero/AGENTS.md`.
- `cash/`: Cash fare collection and cash-price normalization. This module should calculate comparable paid-ticket prices for the same route/date/cabin searched in `seat_aero/`.
- `award_web/`: Browser-controlled award checks for programs or partners that are missing, tentative, or not confirmed by Seats.aero. This module is for Chrome/browser automation and should save evidence plus normalized award rows.

## Intended Data Flow

1. `seat_aero/` searches Seats.aero for a route/date and writes raw JSON plus normalized award rows.
2. `cash/` gathers paid cash fares for the same search context and converts them to normalized USD rows.
3. `award_web/` opens airline or partner award sites in a browser, checks additional availability, and records confirmed or observed options.
4. A future root-level orchestrator can merge all normalized rows and compute final recommendations.

## Shared Record Contract

Each module should eventually emit rows that can be joined by route/date/flight/cabin:

- `origin`, `destination`, `departure_date`
- `depart_time`, `arrive_time`, `flight_numbers`, `carriers`, `cabin`, `stops`
- `source_type`: `seat_aero_award`, `cash`, or `web_award`
- `source_name`: mileage program, cash provider, or website checked
- `points`, `cash_price_usd`, `taxes_usd`, `effective_usd`
- `bookable`, `remaining_seats`, `confidence`, `evidence_path`
- `score`, `flags`, `created_at`

## Scoring Direction

- `config/search_preferences.yaml` is the shared source of truth for point values, FX behavior, time penalties, dynamic price filtering, and cash/award scoring.
- Module-specific preferences should stay inside the owning module only when they are not shared across the pipeline.
- Compare paid cash fares and award effective USD in the same currency, then add comfort and timing penalties consistently.
- Keep full outputs even when rows are expensive, unbookable, or low confidence. Best-flight reports can filter them, but raw evidence should remain available.

## Operating Conventions

- Keep secrets in module-level `.env` files and templates in `.env.example`; never write real keys into docs.
- Treat browser-found award prices as observations unless the site reaches a clear confirmation or checkout-ready state.
- Keep Seats.aero `/routes` data out of the best-flight ranking flow. It is broad route metadata, not one-day priced availability.
- Treat Seats.aero timestamps as displayed local wall-clock strings despite the trailing `Z` until timezone behavior is separately validated.
- The root `.venv/` can be shared by all modules, but module dependencies should be listed inside the module that needs them.

## Code Maintenance Learnings

- Keep shared behavior at the root. Cross-module helpers belong in `flight_search_common/`; shared scoring and valuation settings belong in `config/search_preferences.yaml`.
- Keep provider-specific details inside the owning module. Seats.aero API code stays in `seat_aero/`; cash-provider collection and normalization stay in `cash/`.
- Do not make `seat_aero/` the hidden source of truth for cash behavior. If both cash and awards need a setting or helper, pull it out to the root.
- Keep `AGENTS.md` focused on architecture, editing conventions, and code-improvement rules. Do not turn it into a runbook for executing searches.
- Use the project-local `$flight` skill in `.codex/skills/flight/` for procedural flight-search work: starting the local API, refreshing live data, regenerating reports, and summarizing route results.
- Preserve raw and full normalized outputs. Filtering, ranking, and presentation should happen in reports, not by deleting evidence.
- Prefer reproducible report builders over hand-assembled summaries. `scripts/build_price_summary.py` should generate markdown and HTML from normalized cash and award files.
- Use `scripts/run_trip_search.py` for multi-airport, multi-date, return-trip comparisons. It should expand one-way award legs, one-way cash legs, and real two-leg cash itineraries, then write a traveler-facing master HTML report.
- `scripts/run_trip_search.py` can run independent searches concurrently with `--award-workers` and `--cash-workers`. Keep defaults modest because cash uses `fli`, which also expands return choices internally; prefer `--cash-workers 2` or `3` for live grids and `1` for debugging.
- Mixed cash+award plans should combine a real one-way cash fare with a one-way award leg. For paid-only cash recommendations, compare actual round-trip/open-jaw fares against two separately priced one-ways for the same trip. If two one-ways are cheaper or the same price, prefer them because they are more flexible; still keep the actual two-leg fare visible as the baseline comparison.
- Cash rows for return trips should carry `legs.outbound`, `legs.return`, `cash_detail_status`, and `cash_detail_source` when available. Do not treat missing return timing as a score penalty unless the shared preferences explicitly add such a rule; show it as a data-quality warning in reports.
- The cash module can use `punitarani/fli` (`flights` on PyPI) for structured Google Flights results. It requires Python `>=3.10`. For selected round-trip and open-jaw tuples, live booking checks showed the final segment price is the real complete-itinerary fare; the original outbound price can be only a "from" price after return expansion.
- The combined report may infer cash flight numbers by matching award rows on carrier, departure time, arrival time, and stop count. Keep this inference in final reporting unless a future cash provider can emit exact flight numbers directly.
- Avoid exposing implementation provider names to users when a clearer label exists. For example, final reports should show cash as `cash`, not `fast-flights`.
- HTML reports should remain static and portable: embedded CSS/JS, sortable columns, useful filters, and no dependency on a running app after the file is generated.

## Verification Expectations

- For code edits, run the focused unit tests for touched modules:
  - `python -m unittest cash.tests.test_cash_search`
  - `python -m unittest seat_aero.tests.test_find_best_flights`
- For report-generator edits, regenerate the SFO-DTW fixture report and verify the HTML loads, filters, and sorts.
- For syntax-only confidence, use a writable bytecode cache prefix, such as `PYTHONPYCACHEPREFIX=/private/tmp/flight_search_pycache python -m compileall -q ...`.
- For project-local skill validation, run the skill-creator validator from its system skill location:
  `python /Users/dengcy/.codex/skills/.system/skill-creator/scripts/quick_validate.py .codex/skills/flight`.
