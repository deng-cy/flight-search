# Award Web Checks

Use this module for browser-driven award searches that complement Seats.aero.

Implemented providers:

- Delta public no-login award checks through `delta/scripts/search_delta_awards.py`
- Southwest public one-way points checks through `southwest/scripts/search_southwest_awards.py`
- screenshots and HTML evidence under `data/raw/<provider>/`
- normalized `web_award` rows under `data/normalized/`
- markdown summaries under `data/reports/`
- Provider-specific code is isolated in `delta/` and `southwest/`; the older `scripts/search_delta_awards.py` path is a compatibility wrapper.
- `award_web.run_pipeline(source_name="delta" | "southwest", ...)` dispatches through the shared provider registry in `config/provider_catalog.yaml`.

Cached one-way `web_award` rows are now integrated into the root report builders:

- `scripts/build_price_summary.py` auto-loads matching rows unless `--no-award-web` is passed.
- `scripts/run_trip_search.py` uses matching one-way rows as additional award legs unless `--skip-award-web` is passed.
- Both report builders accept `--award-web-sources delta,southwest` to control which cached web observations are included.
- Round-trip Delta web captures appear in the master trip report as web award observations. If the raw payload includes both `outbound` and `return` snapshots, the report shows parsed return timing; older outbound-only captures remain marked as return selection not parsed.

Install provider dependencies when live browser checks are needed:

```bash
.venv/bin/python -m pip install -r award_web/requirements.txt
.venv/bin/python -m playwright install chromium
```

One-way example:

```bash
.venv/bin/python award_web/delta/scripts/search_delta_awards.py \
  --origin SFO \
  --destination DTW \
  --date 2026-10-14 \
  --trip-type one-way \
  --refresh
```

Round-trip example:

```bash
.venv/bin/python award_web/delta/scripts/search_delta_awards.py \
  --origin SFO \
  --destination DTW \
  --date 2026-11-13 \
  --trip-type round-trip \
  --return-date 2026-11-29 \
  --refresh
```

If Delta blocks the standalone Playwright browser but works in the user's real Chrome session, capture the visible outbound and return pages with the browser tool and import the payload instead of using `--refresh`:

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

Delta errors such as `SFAF009` are saved as provider failures with evidence.
They should not be interpreted as no-availability results.

Southwest one-way example:

```bash
.venv/bin/python award_web/southwest/scripts/search_southwest_awards.py \
  --origin SFO \
  --destination DTW \
  --date 2026-06-12 \
  --refresh
```

The important design difference is that Southwest award trips should be searched as independent one-ways and summed in the report, while Delta web round trips should be searched as true Delta round trips. Southwest round-trip award-web rows are ignored by the root report adapter to avoid accidentally comparing the wrong search semantics.
