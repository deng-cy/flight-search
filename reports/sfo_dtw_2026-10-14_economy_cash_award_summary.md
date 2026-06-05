# SFO to DTW Cash and Award Summary on 2026-10-14

- Cabin: `economy`
- Cash source: `/Users/dengcy/Library/Mobile Documents/com~apple~CloudDocs/Agent/Flight_search/cash/data/normalized/sfo_dtw_2026-10-14_economy_cash_fares.json`
- Award source: `/Users/dengcy/Library/Mobile Documents/com~apple~CloudDocs/Agent/Flight_search/seat_aero/data/sfo_dtw_2026-10-14_best_flights.json`

Cash rows are observed comparable paid fares. Award rows use configured point valuations to compute effective USD.

Score starts with effective USD, then adds penalties for stops, duration, next-day arrival, and inconvenient departure/arrival times. Award rows can receive a small remaining-seat credit.

| Type | Rank | Depart | Arrive | Flight or Carrier | Stops | Duration | Price | Effective USD | Score | Notes |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| cash | 1 | 11:40 | 20:55 | Southwest | 1 | 6 hr 15 min | $195.00 | USD 195.00 | 276.25 | provider_price_level:typical |
| cash | 2 | 07:54 | 17:17 | AA3250, AA4967 | 1 | 6 hr 23 min | $209.00 | USD 209.00 | 290.92 | provider_price_level:typical |
| cash | 3 | 12:47 | 22:12 | AA2334, AA2121 | 1 | 6 hr 25 min | $209.00 | USD 209.00 | 291.08 | provider_price_level:typical |
| cash | 4 | 13:19 | 22:54 | AA2358, AA6291 | 1 | 6 hr 35 min | $209.00 | USD 209.00 | 291.92 | provider_price_level:typical |
| cash | 5 | 07:30 | 17:45 | AA304, AA245 | 1 | 7 hr 15 min | $209.00 | USD 209.00 | 295.25 | provider_price_level:typical |
| cash | 6 | 10:45 | 21:13 | AA1849, AA2508 | 1 | 7 hr 28 min | $209.00 | USD 209.00 | 296.33 | provider_price_level:typical |
| cash | 7 | 10:20 | 22:40 | Southwest | 1 | 9 hr 20 min | $200.00 | USD 200.00 | 296.67 | provider_price_level:typical |
| cash | 8 | 12:22 | 22:57 | American | 1 | 7 hr 35 min | $209.00 | USD 209.00 | 296.92 | provider_price_level:typical |
| cash | 9 | 07:30 | 18:51 | AA304, AA2822 | 1 | 8 hr 21 min | $209.00 | USD 209.00 | 300.75 | provider_price_level:typical |
| cash | 10 | 11:28 | 22:54 | AA2885, AA6291 | 1 | 8 hr 26 min | $209.00 | USD 209.00 | 301.17 | provider_price_level:typical |
| award | 1 | 14:25 | 22:00 | DL717 | 0 | 4h 35m | AF 16,000 + $20.44 | USD 196.44 | 201.36 |  |
| award | 2 | 06:00 | 13:36 | DL772 | 0 | 4h 36m | AF 16,000 + $20.44 | USD 196.44 | 251.44 | early departure |
| award | 3 | 07:54 | 17:17 | AA3250, AA4967 | 1 | 6h 23m | AS 15,000 + $18.10 | USD 243.10 | 307.02 |  |
| award | 4 | 12:47 | 22:12 | AA2334, AA2121 | 1 | 6h 25m | AS 15,000 + $18.10 | USD 243.10 | 307.18 |  |
| award | 5 | 13:19 | 22:54 | AA2358, AA6291 | 1 | 6h 35m | AS 15,000 + $18.10 | USD 243.10 | 320.02 |  |
| award | 6 | 09:45 | 22:12 | AA2414, AA2121 | 1 | 9h 27m | AS 15,000 + $18.10 | USD 243.10 | 322.35 |  |
| award | 7 | 11:28 | 22:54 | AA2885, AA6291 | 1 | 8h 26m | AS 15,000 + $18.10 | USD 243.10 | 327.27 |  |
| award | 8 | 10:27 | 18:12 | UA1286 | 0 | 4h 45m | UA 26,700 + $5.60 | USD 326.00 | 331.75 |  |
| award | 9 | 09:00 | 21:04 | AA2814, AA4885 | 1 | 9h 4m | AS 15,000 + $18.10 | USD 243.10 | 334.43 |  |
| award | 10 | 22:35 | 06:26 +1 | UA1986 | 0 | 4h 51m | UA 15,000 + $5.60 | USD 185.60 | 341.85 | next_day_arrival, late departure |
