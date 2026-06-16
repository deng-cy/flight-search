# Southwest Award Web

This folder owns Southwest-specific browser award checks.

## Contents

- `provider.py`: Southwest public one-way points-search browser automation.
- `normalization.py`: Southwest result-page parsing into shared `web_award` rows.
- `pipeline.py`: Southwest fetch, evidence, normalization, CSV/JSON/report writing.
- `scripts/search_southwest_awards.py`: Southwest CLI entrypoint.

## Important Behavior

Southwest award-web searches are one-way only in this project. For a return trip, run one search per outbound candidate date and one search per return candidate date, then let the root trip report combine compatible one-way rows into award pairs.

Do not emit Southwest `round-trip` web-award rows. The root report adapter ignores them defensively.

## Live Smoke Note

The initial SFO-LAS headless smoke test filled the public one-way points form and saved evidence, but Southwest's shopping API returned HTTP 403 before results were displayed. The parser and report integration are ready for captured result text; the live browser path needs additional anti-bot/session hardening before it can reliably produce normalized rows.
