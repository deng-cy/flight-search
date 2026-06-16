# Southwest Award Web Plan

Southwest award pricing should be modeled as independent one-way searches. Unlike Delta, do not run or preserve a separate round-trip award search for Southwest just to price a return trip.

Status: initial provider, parser, pipeline, CLI, and report one-way aggregation tests are implemented. The live browser path saves evidence conservatively. The first headless SFO-LAS smoke test filled the one-way points form, then Southwest's shopping API returned HTTP 403 and redirected back to the booking form.

## Search Semantics

For a trip with outbound options `SFO -> DTW` on `2026-06-12` and `2026-06-13`, plus return `DTW -> SFO` on `2026-06-20`:

- Delta web: search `SFO -> DTW 2026-06-12 / DTW -> SFO 2026-06-20` and `SFO -> DTW 2026-06-13 / DTW -> SFO 2026-06-20` as true round trips.
- Southwest web: search `SFO -> DTW 2026-06-12`, `SFO -> DTW 2026-06-13`, and `DTW -> SFO 2026-06-20` as one-ways, then sum compatible outbound and return one-way rows in the master report.

## Implementation Shape

1. Add `award_web/southwest/provider.py`. Done.
   - Open Southwest's public booking flow.
   - Select points mode.
   - Search a single origin, destination, date, passenger count, and cabin/fare family.
   - Save HTML and screenshots as evidence.

2. Add `award_web/southwest/normalization.py`. Done.
   - Parse flight number, carrier, depart/arrive time, stops, duration, points, taxes/fees, and fare brand.
   - Emit the shared `web_award` row contract with `source_name: southwest`.
   - Mark rows as observations unless the page reaches a checkout-ready state.

3. Add `award_web/southwest/pipeline.py`. Done.
   - Reuse the Delta pipeline pattern: request validation, raw evidence paths, normalized JSON/CSV, and markdown report.
   - Force `trip_type="one-way"` for Southwest award-web searches.
   - Reject or decompose round-trip requests at the orchestrator layer instead of sending round-trip searches to Southwest.

4. Add `award_web/southwest/scripts/search_southwest_awards.py`. Done.
   - CLI accepts one origin, destination, departure date, passengers, output directory, refresh flag, and headed/headless mode.

5. Extend report integration. Done.
   - Keep one-way Southwest rows discoverable via `flight_search_common.web_awards.load_web_award_rows`.
   - In `scripts/run_trip_search.py`, use existing award-pair logic to combine outbound and return Southwest one-ways.
   - Do not create `web award round-trip` rows for Southwest.

6. Add tests. Done.
   - Unit test parser with mocked Southwest result text.
   - Test that one-way Southwest rows adapt into report award rows.
   - Test that a return-trip search plan combines Southwest one-ways rather than expecting Southwest round-trip rows.

## Open Checks Before Coding

- Confirm whether Southwest's public points search requires login for any route/date. Public points mode is visible without login, but headless result navigation currently hits a shopping API 403.
- Confirm whether taxes are displayed on the results page or only after selecting a fare.
- Confirm whether fare families need separate rows or a single lowest-points row per flight.
