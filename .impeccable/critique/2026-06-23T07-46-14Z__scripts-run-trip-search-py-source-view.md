---
target: scripts/run_trip_search.py source view
total_score: 22
p0_count: 0
p1_count: 2
timestamp: 2026-06-23T07-46-14Z
slug: scripts-run-trip-search-py-source-view
---
#### Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Counts and timestamps are visible, but health state is not. “No rows” does not say whether the run succeeded, failed, or needs action. |
| 2 | Match System / Real World | 2 | Labels expose pipeline concepts like rows, normalized counts, and source files more than traveler-facing outcomes such as checked successfully, no fare found, failed, stale, or partial coverage. |
| 3 | User Control and Freedom | 3 | Users can switch to Source and expand groups, but they cannot filter to empty/degraded sources or jump from a summary card to the affected rows. |
| 4 | Consistency and Standards | 3 | The table structure is consistent, but status vocabulary is too shallow: Rows found, No rows, Issue. |
| 5 | Error Prevention | 2 | “Provider issues: None” can coexist with many 0-row sources, which can incorrectly reassure users that coverage is complete. |
| 6 | Recognition Rather Than Recall | 2 | Users must remember what “Two-leg cash searches 10 of 16” means, then inspect collapsed tables to discover which six are empty. |
| 7 | Flexibility and Efficiency | 2 | Source evidence is complete, but triage is slow because empty rows are not surfaced or grouped by severity/impact. |
| 8 | Aesthetic and Minimalist Design | 3 | The page is visually restrained and stable, but nine equal summary cards flatten what is important. |
| 9 | Error Recovery | 1 | Issue rows are marked, but empty successful rows have no next step: refresh, ignore, add source, check route manually, or treat as no availability. |
| 10 | Help and Documentation | 2 | Short card descriptions help, but there is no legend explaining source health states or when 0 rows is expected. |
| **Total** | | **22/40** | **Useful evidence page, weak diagnostic UX.** |

#### Anti-Patterns Verdict

**LLM assessment**: This does not look like decorative AI UI. It is a pragmatic product page with restrained cards, dense tables, timestamps, and source paths. The problem is not visual slop; it is semantic thinness. The page reports facts but does not interpret their operational meaning.

**Deterministic scan**: The detector found 3 issues in each generated report: Inter as an overused font, single-font usage, and numbered-section-marker advisory. For this product register, the single Inter-style stack is acceptable and mostly a false positive. The numbered marker finding is also a false positive from functional Build Trip step labels. The detector did not catch the actual Source-page problem because the problem is data-state semantics, not a visual anti-pattern.

**Visual overlays**: Browser overlay injection was unavailable because local Playwright/Chromium/browser tooling was not installed in this workspace. Evidence came from generated HTML, CSS, and static detector output.

#### Overall Impression

The Source view is a good audit log but a weak health dashboard. A technical user can see what happened; a traveler or future maintainer cannot confidently tell whether each source is healthy, empty-but-normal, stale, missing, degraded, or broken. The biggest opportunity is to turn row counts into explicit source-health states with explanations and actions.

#### What's Working

- The page preserves useful evidence: each source row has search context, counts, last-updated time, status, and file path.
- The grouping by Seats.aero awards, two-leg cash fares, and one-way cash fares matches the pipeline architecture.
- Summary cards give a fast overview of coverage, such as “Two-leg cash searches 10 of 16” and “One-way cash searches 8 of 8.”

#### Priority Issues

**[P1] “No rows” is not a health state**
**Why it matters**: A 0-row successful search is different from a provider failure, missing parser output, stale cache, route coverage gap, or expected no-availability result. The current status collapses all successful empties into “No rows,” so users cannot tell whether to trust it or fix something.
**Fix**: Replace `source_status()` with a structured source-health model: `ok`, `empty_checked`, `partial`, `stale`, `missing`, `issue`. Render badges like “Healthy,” “Checked: no matching rows,” “Partial coverage,” and “Needs attention,” with one short reason.
**Suggested command**: `$impeccable clarify source page`

**[P1] Summary cards hide empty/degraded coverage**
**Why it matters**: The DTW report says “Provider issues: None” while 6 of 16 two-leg cash searches have 0 rows. The FCA/MSO report says “Provider issues: None” while there are 8 empty Seats.aero award searches, 7 empty two-leg cash searches, and 6 empty one-way cash searches. That can make users believe the data is fully healthy when coverage is actually incomplete.
**Fix**: Add an “Attention needed” or “Empty checked” summary card that counts empties separately from issues, and include impacted groups: “6 empty two-leg cash searches; 0 provider failures.”
**Suggested command**: `$impeccable clarify source page`

**[P2] Collapsed groups make 0-row rows too easy to miss**
**Why it matters**: `source_detail_group()` opens only when `status == "Issue"`. Empty sources are not issues, so groups with meaningful data gaps remain collapsed. Users see only “16 searches,” not “6 empty.”
**Fix**: Include empty counts in group headers and auto-open groups with issues or empties. Example: “Two-leg cash fares · 16 searches · 6 empty · 0 failed.” Add a filter/toggle for “Show attention rows.”
**Suggested command**: `$impeccable layout source page`

**[P2] Card labels describe implementation, not user impact**
**Why it matters**: Labels like “Award flight rows” and “One-way routes priced” explain row inventory, but not whether the report can support a decision. “Cash timing verified 10 of 10” sounds fully healthy even when six searched cash itineraries returned no fares.
**Fix**: Rename cards around coverage and confidence: “Trip plans available,” “Round-trip/open-jaw cash coverage,” “One-way cash coverage,” “Award coverage,” “Data concerns.” Each card should include success, empty, failed, and impact.
**Suggested command**: `$impeccable clarify source page`

**[P3] Source paths dominate the right edge without becoming actionable**
**Why it matters**: File paths are useful for developers but are not the first thing a traveler needs. They also visually compete with health state and update time.
**Fix**: Keep file paths available, but move them behind a “File” disclosure or make the column visually secondary after a clearer “Meaning / action” column.
**Suggested command**: `$impeccable distill source page`

#### Persona Red Flags

**First-time traveler**: They see “Provider issues: None” and assume all sources are healthy. They will not know that “10 of 16” means six cash itinerary combinations produced no fare rows, nor whether that matters for the recommendation.

**Power user / maintainer**: They can find files and counts, but still have to mentally classify each empty source. They need a triage list: failed runs, empty successful runs, stale files, and low-coverage routes.

**Price-sensitive planner**: They care whether the cheapest plan is based on complete coverage. The Source page does not tell them whether missing/empty rows changed the recommendation set, especially for mixed cash + award plans.

#### Minor Observations

- “Cached Allowed” reads like an internal enum. “Using cached data” or “Live + cached” would be clearer.
- “Rows found” is too generic; “Options found” is better for users, while “rows” can stay in developer details.
- “Provider issues” only means exceptions/provider errors today. It should not be the only visible health metric.
- The source table has no legend, so users cannot learn the difference between empty, issue, stale, and healthy states.
- The page is dense but acceptable for a product tool; the main fix is better hierarchy and state language, not a prettier skin.

#### Questions to Consider

- Should 0 rows be treated as “checked successfully, no matching options” by default, or should some routes/programs be marked as “coverage gap” when the provider is known to miss them?
- Do you want this page optimized for travelers deciding whether to trust the report, or for you debugging pipeline runs? The best labels differ slightly.
- Should empty sources affect the top Summary page with a warning, or stay contained in Source unless they change recommendation confidence?
