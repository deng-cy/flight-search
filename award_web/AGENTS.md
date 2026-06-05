# Award Web Module

This folder owns browser-controlled award searches for sources that are not fully covered or confirmed by Seats.aero.

## Responsibilities

- Control a browser to search airline and partner award sites for additional availability.
- Save screenshots, HTML snapshots, or structured observations as evidence.
- Normalize confirmed or observed award rows into the shared pipeline contract.
- Mark each row with a confidence level, since website results can be tentative until checkout.

## Use Cases

- Verify partner availability that Seats.aero omits, such as a partner website showing a tentative award price.
- Search programs that are not returned as priced `Source` rows in Seats.aero.
- Capture evidence when a site displays a fare but does not provide a simple API response.

## Evidence Rules

- Save enough context to explain the result later: route, date, program, flight number, cabin, points, taxes, and screenshot or HTML evidence path.
- Treat award web rows as observations until the website reaches a clear bookable state.
- Do not overwrite Seats.aero confirmed priced rows. Add web findings as separate sources.

## Future Implementation Notes

- Prefer reusable Python browser automation where possible.
- If direct Chrome control is required, use the Codex Chrome/browser capability available in the current environment and keep site-specific workflows isolated by program.
- Store credentials outside this folder in an ignored `.env` file if a site login is ever needed.
