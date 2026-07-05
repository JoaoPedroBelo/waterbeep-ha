# Waterbeep API (reverse-engineered, verified live)

Waterbeep has **no public API**. This integration drives the same HTTP endpoints
the web dashboard at `https://www.aquamatrix.pt/waterbeep/` uses. The backend is
the **Aquamatrix SMSnet** platform (ASP.NET Core).

## Auth flow (verified)

1. `GET /waterbeep/Account/Login` → sets the antiforgery cookie and embeds a
   hidden `__RequestVerificationToken` in the HTML.
2. `POST /waterbeep/Account/Login` (form-encoded) with `UserCode` (the NIF),
   `Password`, `__RequestVerificationToken`. On success it **redirects to
   `/waterbeep/Dashboard/Modalities`** and sets the `.AspNetCore.Cookies`
   session cookie.
3. **The landing page embeds the token reused for AJAX calls** — scrape it from
   the login-POST response body (not from `/waterbeep/Dashboard`, which has none).
4. `POST /waterbeep/Dashboard/Get*` with the token **in the body** plus
   `X-Requested-With: XMLHttpRequest`. No header token, no cookie pairing.

## Endpoints (all POST, verified live)

| Endpoint | Body | Returns |
|----------|------|---------|
| `Dashboard/GetLastSevenDaysChart` | token | daily m³, 7 days |
| `Dashboard/GetLastThirtyDaysChart` | token | daily m³, 30 days |
| `Dashboard/GetLastConsumptionReadingsChart` | token | **monthly** m³ (billed) |
| `Dashboard/GetCapitationConsumption` | `numberOfInhabitants=N` | monthly L/person/day |
| `Dashboard/GetClientNotifications` | none | alerts (`data: null` when none) |

## Response shape (verified)

Daily / monthly charts:

```json
{"succeed": true, "data": {
  "labels": ["2 Jul 2026", ...],
  "years":  [2026, ...],
  "months": [7, ...],
  "days":   [2, ...],
  "values": [0.231, 0.592, 0.032, 0.005, 0.0, ...],
  "averageDailyConsumption": 0.1228
}}
```

- Daily `values` are **m³ per day**; `values` run oldest → newest.
- Monthly (`GetLastConsumptionReadingsChart`) `values` are **m³ per month** (not a
  cumulative index — confirmed: they go down as well as up).
- Capitation `values`/`averageDailyConsumption` are **litres per person per day**.
- A session that has expired serves the HTML login page instead of JSON → the
  client treats a non-JSON response as an auth error and re-logs-in once.

## Energy/Water dashboard note

None of these endpoints exposes a cumulative meter index. The
`Total Consumption` sensor therefore synthesises a monotonic
`total_increasing` value by accumulating each newly completed day exactly once
(`coordinator.accumulate_total`), persisting the running total + a date cursor
across restarts. A fresh install seeds the cursor to the newest complete day so
history is not imported as a one-off spike.

> The captured `UserCode`/`Password`/tokens are per-session and must never be
> committed. The `UserCode` is the account holder's NIF.
