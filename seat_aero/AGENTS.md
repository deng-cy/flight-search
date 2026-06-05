# Agent Notes

## Seats.aero API Wrapper

- This project uses Python/FastAPI as a thin local wrapper around the Seats.aero Partner API.
- Keep the Seats.aero key in `seat_aero/.env`; do not commit secrets. `.env.example` is the portable template.
- From the workspace root, run the API with:

```bash
source .venv/bin/activate
cd seat_aero
uvicorn app.main:app --reload
```

- Useful local endpoints:
  - `GET /search` for cached route/date searches.
  - `GET /trips/{availability_id}` for segment-level details and booking links.
  - `GET /routes?source=...` for all tracked routes for a source program. This is broad and should not be used for simple one-day pricing checks.

## Important Seats.aero Semantics

- Treat `Source` as the priced mileage program. If a result says `Source: "delta"`, the mileage fields are Delta-sourced prices, not prices from every partner that can theoretically book the flight.
- Treat `booking_links` as convenience links, not proof of priced availability. A Delta result may include links like "Book via Virgin Atlantic" or "Book via Air France/KLM Flying Blue" even when the payload does not include Virgin or Flying Blue mileage pricing.
- A partner program has confirmed pricing only when it appears as its own `Source` result, such as `source: "virginatlantic"` or `source: "flyingblue"`.
- `AvailabilityTrips` in the search response is useful for quick ranking, but `/trips/{availability_id}` is needed for flight numbers, segment details, aircraft, booking links, and direct/nonstop comparisons.

## Findings From Test Searches

- `DTW -> SFO` on `2026-05-26` returned priced sources: `aeroplan`, `alaska`, `american`, `azul`, `delta`, and `united`.
- For that DTW-SFO search, Delta results had a Virgin Atlantic booking link, but there was no `virginatlantic` priced source. A targeted `sources=virginatlantic` search returned zero results.
- `SFO -> DTW` on `2026-10-14` returned priced sources including `virginatlantic` and `flyingblue`.
- For `SFO -> DTW` on `2026-10-14`, DL717 appeared as:
  - Delta: 31,700 miles + USD 5.60 in economy.
  - Virgin Atlantic: 22,000 points + USD 5.60 in economy.
  - Flying Blue: 16,000 miles + USD 20.44 in economy.
- Korean Air/SKYPASS did not appear in the saved raw results or booking links for the SFO-DTW search. Targeted checks with `sources=koreanair`, `sources=korean`, and `sources=skypass` all returned zero results.
- Working interpretation: if Seats.aero cannot confirm mileage pricing for a partner program, it may omit that partner as a priced source even if the partner's own website appears to show theoretical or tentative availability.

## Saved Data

- Raw and summarized search files are under `seat_aero/data/`.
- `scripts/save_search_raw.py` saves a one-day raw search plus optional trip-detail payloads.
- `scripts/save_routes_raw.py` saves broad route lists by source. Use sparingly because route lists contain thousands of tracked routes and are not needed for one-day partner-pricing checks.

## Best-Flight Ranking Pipeline

- Root `config/search_preferences.yaml` is the central place for reusable ranking preferences: traveler defaults, point values, FX behavior, scoring weights, time penalties, and dynamic price filtering.
- `scripts/find_best_flights.py` is the reusable pipeline for route/date searches. It preserves raw Seats.aero JSON, normalizes every priced `Source` row, converts taxes to USD, scores candidates, writes full outputs, and writes deduped best-flight reports.
- Daily FX uses Frankfurter at `https://api.frankfurter.dev/v2/rates?base=USD`; snapshots are cached under `data/fx/`. If live FX fails, the script uses the latest cache; if no cache exists, non-USD rows are marked non-comparable.
- Effective USD is `points * cents_per_point / 100 + converted_taxes_usd`.
- Balanced score starts with effective USD, then applies configured soft penalties for stops, travel duration, next-day arrival, early/late departure, late/after-midnight arrival, and a small seat-count credit.
- Rows with `RemainingSeats < passengers` are kept in the full normalized output with `bookable=false`, but excluded from best-flight output.
- Very pricey rows are not deleted. They are marked with `expensive_flag=true` in full output and hidden only from the best-flight report.
- The best-flight report deduplicates same flight/time/cabin combinations by selecting the lowest score as primary and listing other bookable priced programs in `alternates`.
- Treat Seats.aero timestamps as displayed wall-clock times despite the trailing `Z`; do not timezone-convert unless airport timezone behavior is separately validated.
