# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
