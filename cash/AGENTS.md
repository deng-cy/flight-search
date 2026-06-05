# Cash Fare Module

This folder owns paid cash fare discovery and normalization. It should answer: "What would this flight or a comparable itinerary cost in dollars?"

## Responsibilities

- Search cash fares for the same route/date/cabin context used by `seat_aero/`.
- Normalize paid fares into USD, including base fare, taxes, and fees when available.
- Save raw provider responses or browser evidence before producing cleaned rows.
- Emit comparable rows that can be merged with award rows for final value ranking.

## Preferred Outputs

- `data/raw/`: raw cash fare responses or captured evidence.
- `data/normalized/`: normalized CSV/JSON with one row per cash option.
- `data/reports/`: markdown or CSV summaries for quick inspection.

## Normalized Fields

Use the shared root contract where possible: `origin`, `destination`, `departure_date`, `depart_time`, `arrive_time`, `flight_numbers`, `carriers`, `cabin`, `stops`, `cash_price_usd`, `bookable`, `confidence`, `evidence_path`, and `flags`.

## Notes

- Cash fares should be treated as a comparison baseline for award effective USD.
- If a cash fare source returns multiple fare brands, keep the cheapest sensible fare and mark restrictive fares in `flags`.
- If exact flight matching is unavailable, keep comparable itineraries but flag them as `not_exact_flight`.
