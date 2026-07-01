# Flight Search Workspace

This workspace contains a three-stage flight comparison pipeline:

- `seat_aero/` captures and ranks award availability from the local Seats.aero wrapper.
- `cash/` captures and normalizes paid fare observations.
- `award_web/` captures browser-observed award checks, starting with no-login Delta searches.

Shared, cross-module helper code lives in `flight_search_common/`. Shared ranking preferences live in `config/search_preferences.yaml`. Keep provider-specific code and provider-owned data inside the module that owns it.

## Recommended Setup

If you use Codex or Claude Code, start with the repo-local `setup` skill instead of running the setup script directly. Ask the agent to use the `setup` skill for this repository; it will guide local Seats.aero credentials, traveler scoring preferences, Python environment setup, and machine-specific files without overwriting tracked defaults.

For flight-search work, prefer the repo-local `flight` skill when using Codex. It knows the project workflow for starting the local API, refreshing award and cash data, and regenerating reports.

The direct setup script is still available as a fallback for manual use:

```bash
python3 agent_skills/setup/scripts/setup_repo.py
```

## Common Commands

Run the award ranking from cached Seats.aero data:

```bash
python seat_aero/scripts/find_best_flights.py --origin SFO --destination DTW --date 2026-10-14 --offline-fx
```

Run the cash fare normalizer:

```bash
python cash/scripts/search_cash_fares.py --origin SFO --destination DTW --date 2026-10-14 --cabin economy --currency USD
```

Build a combined cash and award report:

```bash
python scripts/build_price_summary.py --origin SFO --destination DTW --date 2026-10-14 --cabin economy
```

The combined report is written under `reports/`.
It automatically includes matching cached one-way `award_web` rows when they exist; use `--no-award-web` to suppress them or `--award-web-json` to pass specific files.

Run a multi-airport return-trip search with real two-leg cash pricing:

```bash
python scripts/run_trip_search.py \
  --origins SFO,SJC \
  --destinations FCA,MSO \
  --outbound-dates 2026-09-04,2026-09-05 \
  --return-dates 2026-09-07 \
  --cabin economy \
  --base-url http://127.0.0.1:8001
```

The master trip report is written under `reports/`. Cash recommendations use actual `round-trip` or `multi-city` provider searches; award recommendations are built from one-way outbound and return award legs. Cash rows show whether return timing was verified, outbound-only, or price-only.
Cached one-way `award_web` observations are included as additional award legs unless `--skip-award-web` is passed. Cached round-trip web observations are shown as tentative web award rows when the return leg has not been parsed yet.
