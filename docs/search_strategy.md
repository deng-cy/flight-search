# Flight Search Strategy

Round-trip travel should be searched as combinable one-way inventory first, with true two-leg pricing added only when a provider can price a complete trip differently.

## Provider Rules

- Seats.aero awards: search each outbound and return leg as a one-way award. Pair compatible legs in the trip report as `award pair` plans.
- Cash fares: search every one-way leg and every actual two-leg itinerary. The two-leg search should use `round-trip` for exact reverse returns and `multi-city` for open-jaw returns.
- Southwest points: search one-way award legs only. Southwest round trips are modeled as the sum of two one-way point prices, so a separate Southwest round-trip award search is not useful.
- Delta and other true-round-trip award-web providers: keep true round-trip observations when `round_trip_mode: true_round_trip`, but keep one-way observations available for award pairs and mixed cash+award plans.

## Recommendation Rules

- One-way cash rows are core search inputs. They support mixed cash+award plans and two-one-way paid comparisons.
- True round-trip/open-jaw cash rows are the baseline for paid fares because cash providers can price complete itineraries differently from separate one-ways.
- If two one-way cash tickets are cheaper than or the same price as the exact same trip's true two-leg cash fare, surface the two-one-way strategy as the preferred paid strategy because it is more flexible.
- Keep the true two-leg cash fare visible even when two one-ways are preferred, so the traveler can compare price, timing, and booking friction.

## Source Of Truth

Provider capabilities belong in `config/provider_catalog.yaml`.

- `supported_trip_types` says which trip types the provider can search directly.
- `round_trip_mode: true_round_trip` means cached round-trip award-web rows can be used as complete observations.
- `round_trip_mode: sum_one_way` or a missing `round-trip` support entry means return-trip reports should rely on summed one-way rows instead of round-trip award-web rows.
