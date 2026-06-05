# Seats.aero Search API

This folder contains the Python/FastAPI wrapper around the Seats.aero Partner API and the award-flight ranking pipeline.

The local API key lives in `seat_aero/.env`, which is ignored by git. Use `.env.example` as the template if you move this project elsewhere.

## Setup

From the workspace root:

```bash
source .venv/bin/activate
cd seat_aero
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open:

- API: `http://127.0.0.1:8000`
- Swagger docs: `http://127.0.0.1:8000/docs`

## Endpoints

- `GET /health`
- `GET /search` maps to Seats.aero cached search.
- `GET /availability` maps to bulk availability.
- `GET /trips/{availability_id}` maps to trip-level flight details.
- `GET /routes` maps to available routes for a mileage program.
- `POST /live` maps to live search, but is disabled unless `SEATS_AERO_ENABLE_LIVE_SEARCH=true`.

## Examples

```bash
curl "http://127.0.0.1:8000/search?origin_airport=SFO&destination_airport=LHR&start_date=2026-06-01&end_date=2026-06-15&take=50&cabins=business"
```

```bash
curl "http://127.0.0.1:8000/routes?source=aeroplan"
```

```bash
curl "http://127.0.0.1:8000/availability?source=aeroplan&cabin=business&take=50"
```

Seats.aero returns the remaining daily request budget in `X-RateLimit-Remaining`; this wrapper forwards it as `X-SeatsAero-RateLimit-Remaining`.

## Notes

- Seats.aero's docs say Pro API access includes cached search, bulk availability, trips, routes, and OAuth.
- Their knowledge base says Live Search is limited to approved commercial partners, so it is guarded by a local feature flag.
- Pro API usage is documented as 1,000 calls per day, resetting at midnight UTC.
- Run `python scripts/find_best_flights.py --origin SFO --destination DTW --date 2026-10-14 --offline-fx` from this folder to regenerate the ranked award-flight outputs from cached data.
- Cross-module helpers live in the root `flight_search_common/` package. Shared scoring and point preferences live in root `config/search_preferences.yaml`.
