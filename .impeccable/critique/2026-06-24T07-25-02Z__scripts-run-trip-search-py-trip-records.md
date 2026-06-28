---
target: Trip records right-panel selector
total_score: 28
p0_count: 0
p1_count: 1
timestamp: 2026-06-24T07-25-02Z
slug: scripts-run-trip-search-py-trip-records
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Current/Open is visible, but retrieval/update freshness is missing from the record selector. |
| 2 | Match System / Real World | 3 | Route and date language is understandable; "Open" is action language masquerading as status. |
| 3 | User Control and Freedom | 3 | Saved reports are easy links; the list has no sort/filter/search once it grows. |
| 4 | Consistency and Standards | 3 | Uses the report's card/chip vocabulary, though record chips carry mixed meanings. |
| 5 | Error Prevention | 2 | Users can open stale saved reports without knowing they are stale. |
| 6 | Recognition Rather Than Recall | 3 | Route, date span, and plan count are visible without opening each report. |
| 7 | Flexibility and Efficiency | 3 | Good for two records; less efficient when many trips accumulate. |
| 8 | Aesthetic and Minimalist Design | 3 | Compact and calm, but metadata is over-compressed into tiny pills. |
| 9 | Error Recovery | 3 | Current page state is clear; no obvious destructive path here. |
| 10 | Help and Documentation | 3 | Labels are mostly self-explanatory, but freshness/source recency needs clearer language. |
| **Total** | | **28/40** | **Solid utility, missing trust-critical freshness.** |

## Anti-Patterns Verdict

This does not look obviously AI-generated at the Trip records level. It reads like a restrained product side rail: familiar, compact, and mostly useful. The current state is a little over-signaled with accent border, tinted background, and an inset left stripe. The page-level detector found Inter/single-font warnings and numbered section markers elsewhere; for this product UI, Inter and a single sans family are acceptable, while the numbered markers are outside this panel.

## Overall Impression

The panel is doing the right job in the right place: it gives quick access to saved trip reports without pulling attention away from the recommendation cards. Its biggest weakness is trust, not decoration. A traveler deciding whether to act on a fare needs to know when each saved result was retrieved before they click.

## What's Working

- The route headline is strong. "SFO/SJC to DTW" is scannable and matches the report title.
- The selected state is unmistakable. Users can tell which report is active at a glance.
- The record cards are compact enough for the side rail and remain keyboard-addressable links.

## Priority Issues

**[P1] Missing retrieval/update time**

Why it matters: flight prices and award availability expire quickly. Without a "Retrieved" or "Updated" timestamp, users cannot judge whether a saved report is safe to compare against the current one.

Fix: Render freshness directly in each record, including the current record. Prefer wording like `Retrieved 2026-06-23 00:42 PDT` or `Retrieved Jun 23, 00:42 PDT`. If space is tight, show `Retrieved Jun 23` with a tooltip/title containing exact time and timezone. Use retrieval/source-data time, not only HTML file mtime.

Suggested command: `$impeccable polish Trip records`

**[P2] Metadata chips mix count, state, and action**

Why it matters: `237 complete plans` is data quality/volume, `Current` is selection state, and `Open` is an action. Presenting all of them as identical pills makes the record harder to parse than it needs to be.

Fix: Keep plan count as a quiet metric. Move selection/action to a top-right badge or remove `Open` entirely because the whole card is already a link. Add freshness as a text metadata row rather than another identical pill.

Suggested command: `$impeccable clarify Trip records`

**[P2] Date line is accurate but heavy**

Why it matters: repeated labels make the second line dense: `Outbound dates: ... · Return dates: ...`. In a narrow side rail, the labels steal attention from the dates.

Fix: Condense to `Outbound Nov 13-14 · Return Nov 29-30` for same-year ranges, while keeping exact ISO dates in title attributes or accessible labels if needed. If ISO dates are preferred for precision, split outbound and return onto two short lines.

Suggested command: `$impeccable layout Trip records`

**[P3] Current styling is slightly over-signaled**

Why it matters: the current record uses accent border, accent background, and a left accent stripe. It is clear, but it competes with the main report's decision cards.

Fix: Keep the full accent border plus soft background, and drop the inset stripe; or keep the stripe and use a neutral border. The calmer version will still be obvious in this compact list.

Suggested command: `$impeccable quieter Trip records`

**[P3] Mobile placement makes saved reports secondary**

Why it matters: under 900px the controls move below the report content. That is reasonable, but Trip records then become hard to discover if the user mainly wants to switch reports.

Fix: On mobile, consider moving only the Trip records block above filters, or collapsing it behind a compact "Saved reports" disclosure near the top.

Suggested command: `$impeccable adapt Trip records`

## Recommended Record Format

```text
SFO/SJC to DTW                         Viewing
Outbound Nov 13-14 · Return Nov 29-30
237 complete plans · Retrieved Jun 23, 00:42 PDT
```

For non-current records:

```text
SFO/SJC to FCA/MSO                     Open
Outbound Sep 4-5 · Return Sep 7
160 complete plans · Retrieved Jun 22, 00:32 PDT
```

## Persona Red Flags

**Price-pressured traveler**: They can see which saved report has more plans, but cannot tell whether the data is fresh enough to trust. This is the highest-risk miss.

**Returning user comparing previous searches**: The list sorts old records by file mtime internally, but the UI does not reveal that recency. They may assume the second record is comparable even if it was retrieved a day or week earlier.

**Mobile reader**: The Trip records block drops below the main report under 900px, so switching saved reports becomes a lower-discoverability task.

## Minor Observations

- `updated_label` exists in the record payload but is not rendered in `trip_record_selector_html`.
- The current record is forced to have no `updated_label`, so the current report needs a real freshness source before display.
- The source-data table already uses `Last updated`, which proves the report has a freshness pattern elsewhere. Trip records should borrow that convention.
- The detector's Inter/single-font warning is a false positive for this product register.

## Questions to Consider

- Should the timestamp mean "report generated", "source files last modified", or "live provider results retrieved"? Those are different trust signals.
- Is plan count the right secondary metric, or should stale/error status outrank it?
- Should `Open` be an explicit chip, or should only the current record receive a state badge?
