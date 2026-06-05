# Cash Fare Checks

Use this module for paid-ticket price discovery. The goal is to produce normalized USD cash fares that can be compared against award `effective_usd` from `seat_aero/`.

## Provider Choice

This implementation uses `flights`/`fli`, the PyPI package from `punitarani/fli`, behind a small adapter. It is a better fit for return-trip comparison because it returns structured Google Flights results, including separate outbound and return segments with times, carriers, and flight numbers when Google exposes them.

Important caveat: it is an unofficial reverse-engineered Google Flights API client, not a booking API. Treat results as observed comparison prices, keep raw evidence, and expect occasional breakage if Google changes internal endpoints or response shapes. The dependency requires Python `>=3.10`.

## Setup

From the workspace root:

```bash
source .venv/bin/activate
pip install -r cash/requirements.txt
```

## Run A Search

```bash
python cash/scripts/search_cash_fares.py \
  --origin SFO \
  --destination DTW \
  --date 2026-10-14 \
  --cabin economy \
  --currency USD
```

By default, the script reuses an existing raw provider response if one is present. Add `--refresh` to fetch a new response.

Set `FLI_TOP_N` to control how many outbound candidates `fli` expands into return/open-jaw combinations. The default is `3`; use `FLI_TOP_N=1` for a quick smoke check, or a larger value when completeness is more important than speed.

## Outputs

- `data/raw/`: raw `fli` provider response.
- `data/normalized/`: normalized CSV/JSON with one row per cash option.
- `data/reports/`: markdown summaries for quick inspection.

Normalized rows follow the shared root contract where possible: `origin`, `destination`, `departure_date`, `depart_time`, `arrive_time`, `flight_numbers`, `carriers`, `cabin`, `stops`, `source_type`, `source_name`, `cash_price_usd`, `bookable`, `confidence`, `evidence_path`, `score`, and `flags`.

Cash `score` uses the shared root `config/search_preferences.yaml` penalties for stops, duration, next-day arrival, and early/late departure or arrival.

For multi-leg paid searches, the adapter uses the final selected `fli` segment as the total itinerary price because live booking-option checks showed that selected return/open-jaw rows carry the real combined fare after outbound expansion.

Cross-module helpers for JSON/CSV writing and display formatting live in the root `flight_search_common/` package.
