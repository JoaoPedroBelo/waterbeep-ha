# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2]

### Fixed
- Requesting the 2FA one-time code failed with "Failed to reach the Waterbeep
  service" (the v0.2.2 fix addressed a different, non-root cause). The server
  binds the 2FA challenge to its ASP.NET session cookie, and the reauth flow
  logs in when the flow is *created* — by the time the user picks a delivery
  channel that session has expired, and `SubmitContact` against the dead
  session makes Waterbeep return HTTP 500. The flow now re-issues the challenge
  (fresh session cookies + `Token`/`EntityCode`) immediately before requesting
  the code.
- 2FA send/submit failures now log the underlying HTTP error (previously
  swallowed), so future issues are diagnosable from the HA log.

## [0.3.1]

### Fixed
- Recent days could be stuck at 0 on the Energy dashboard. Waterbeep publishes a
  day's total with a delay, so a day can still read 0 shortly after it closes and
  fill in later. The importer used a forward-only cursor: it locked a day in on
  first sight (0 included) and never revisited it, so late-arriving values were
  lost. It now re-imports a trailing 7-day window on every poll — anchored on the
  cumulative sum of the last stable day so history stays monotonic — letting late
  values overwrite the earlier 0s.

## [0.3.0]

### Fixed
- The Energy/Water dashboard now matches the official Waterbeep chart day-for-day.
  Previously the `Total Consumption` sensor fed the dashboard a live
  `total_increasing` value, but Waterbeep data is **backdated** — so every day's
  usage was attributed to the poll hour, collapsing the daily distribution into a
  single spike. Consumption is now imported as a long-term **external statistic**
  (`waterbeep:consumption`), timestamped at each day's local midnight, so history
  is placed on the correct days (the full 30-day window on a fresh install, with
  no import spike).

### Changed
- **Breaking:** the `Total Consumption` sensor has been removed. Point the
  Energy dashboard's water source at the **Waterbeep Consumption**
  (`waterbeep:consumption`) statistic instead. The informative Daily / 7-Day /
  30-Day / Monthly / Per-Capita sensors are unchanged.
- The integration now depends on the `recorder` (required for statistics import).

## [0.2.2]

### Fixed
- Two-factor verification no longer fails with "Failed to reach the Waterbeep
  service" when picking a delivery channel. The `SubmitContact`/`SubmitOTP`
  requests now carry the antiforgery `__RequestVerificationToken` scraped from
  the challenge page — like every other request on the site — instead of being
  rejected with HTTP 400. The config flow also logs the underlying error so a
  genuine connection failure is diagnosable from the Home Assistant log.

## [0.2.1]

### Changed
- Re-authentication now reuses the stored password automatically and goes
  straight to the two-factor code step. The password form only appears if the
  stored password is actually rejected — no more redundant password prompt on a
  routine 2FA re-verification.

## [0.2.0]

### Added
- Two-factor authentication support. Waterbeep now enforces risk-based 2FA: a
  login from an untrusted IP is challenged with a one-time code (SMS or email).
  The integration surfaces this through Home Assistant's re-authentication flow —
  pick a delivery channel, then enter the 6-digit code — and re-trusts the
  connection so twice-daily polling resumes.

### Changed
- Authentication and 2FA failures now raise `ConfigEntryAuthFailed`, so Home
  Assistant prompts for re-authentication instead of retrying silently.

### Fixed
- Setup no longer crashes with a misleading "no antiforgery token on the landing
  page" error when Waterbeep challenges the login with 2FA.

## [0.1.1]

### Added
- Local brand images (`brand/icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`)
  served directly by Home Assistant 2026.3+.

## [0.1.0]

### Added
- Initial scaffold of the Waterbeep (EPAL) Home Assistant integration.
- Cloud-polling `DataUpdateCoordinator` architecture (mirrors the BMW Wallbox integration).
- `api.py` client: ASP.NET Core antiforgery + cookie-session login flow
  (`Account/Login`) and `Dashboard/GetLastSevenDaysChart` AJAX call.
- Config flow (User Code + Password) validated by a live login, plus options
  flow for the update interval.
- Sensors: Daily Consumption, 7-Day Consumption. Binary sensor: Service Available.
- English and Portuguese translations.
- CI: tests, HACS + hassfest validation, release workflows.

### TODO
- Capture real response bodies to finalise field mapping (see
  `custom_components/waterbeep/docs/API.md`).
- Add meter index (m³), 30-day, per-person, billing and leak sensors once their
  endpoints are captured.
