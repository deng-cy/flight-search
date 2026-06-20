# Delta Award Web

This folder owns Delta-specific browser award checks.

## Contents

- `provider.py`: Delta public no-login browser automation.
- `normalization.py`: Delta result-page parsing into shared `web_award` rows.
- `pipeline.py`: Delta fetch, evidence, normalization, CSV/JSON/report writing.
- `scripts/search_delta_awards.py`: Delta CLI entrypoint.

Compatibility wrappers remain at the previous `award_web/award_web/*` and `award_web/scripts/search_delta_awards.py` paths so existing imports and commands keep working.

## Outputs

Provider evidence and normalized rows stay in the shared award-web output tree:

- raw Delta evidence: `award_web/data/raw/delta/`
- normalized rows: `award_web/data/normalized/*delta*_web_awards.{json,csv}`
- provider markdown summaries: `award_web/data/reports/*delta*_web_awards.md`

Keeping outputs in the shared tree lets the root report builders discover web-award rows consistently across providers.

## Important Behavior

Delta round-trip checks should use Delta's round-trip UI. Do not replace a Delta round-trip search with two one-way web searches.

The standalone Playwright fetch can be blocked by Delta's edge bot checks. When Delta works in the user's real Chrome session, capture the visible outbound and return pages with the browser tool and save a JSON payload with this shape:

```json
{
  "snapshots": [
    {
      "stage": "outbound",
      "url": "https://www.delta.com/...",
      "body_text": "...visible outbound page text...",
      "html_content": "...optional page html..."
    },
    {
      "stage": "return",
      "url": "https://www.delta.com/...",
      "body_text": "...visible return page text...",
      "html_content": "...optional page html..."
    }
  ]
}
```

Then import and normalize it through the standard Delta pipeline:

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

This writes the usual raw JSON, evidence, normalized CSV/JSON, and markdown report. If both outbound and return snapshots contain parseable flight rows, the normalized row carries `legs.outbound`, `legs.return`, and the flattened `return_*` timing fields used by the master trip report.
