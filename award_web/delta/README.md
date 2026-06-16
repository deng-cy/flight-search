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

Delta round-trip checks should use Delta's round-trip UI. Do not replace a Delta round-trip search with two one-way web searches. The current round-trip parser records the outbound-selection page as an observation and marks return selection as unparsed until the return leg is parsed from Delta's flow.
