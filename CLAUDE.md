# Waterbeep (EPAL) — Home Assistant Integration

Home Assistant custom integration for the **Aquamatrix Waterbeep** water-telemetry
service (EPAL meters).

**Key concept:** Waterbeep has no public API. Home Assistant acts as a **client**
that signs into the Waterbeep web app and reads the same dashboard endpoints the
browser uses (cloud polling).

## Documentation-first

Read the relevant doc in `custom_components/waterbeep/docs/` **before** changing
the API client, coordinator, or entities:

| Doc | Read when |
|-----|-----------|
| `ARCHITECTURE.md` | Component relationships, data flow |
| `API.md` | The reverse-engineered requests + outstanding TODOs |

## Core files

| File | Purpose |
|------|---------|
| `api.py` | **All network logic.** Session, ASP.NET antiforgery, login, endpoint calls. |
| `coordinator.py` | `DataUpdateCoordinator`; normalises raw payloads into `self.data`. Twice-daily schedule. |
| `const.py` | `Final`-typed constants: config keys, entity suffixes, `coordinator.data` keys, `POLL_HOURS`. |
| `config_flow.py` / `__init__.py` | Config UI (validated by a live login) / entry point. |
| `sensor.py` / `binary_sensor.py` | Entities. |

## Critical rules

1. **All network logic in `api.py`.** The coordinator never talks HTTP directly.
2. **All state in the coordinator** — entities read `self.coordinator.data.get(...)`; return `None` for missing values.
3. **The client owns its own cookie jar** — never the shared HA session — so the authenticated session is isolated.
4. **Poll twice a day (01:00 / 13:00)** via `async_track_time_change` — no tight periodic loop. Stay low-profile against Waterbeep's servers.
5. **Never commit real credentials or account codes** (the User Code is a NIF). Use placeholders in tests/docs.
6. **Log via `_LOGGER`** — never `print()` (ruff `T20`).
7. Re-login transparently once on an auth error, then fail the update.

## Development

Prefer the project venv directly (`.venv/bin/...`):

```bash
.venv/bin/ruff check custom_components/ tests/        # lint (blocks CI)
.venv/bin/ruff format custom_components/ tests/       # format
.venv/bin/mypy custom_components/waterbeep            # types (advisory in CI)
.venv/bin/pytest tests/ -q                            # tests
```

Or via Make: `make lint`, `make format`, `make test`, `make coverage`, `make check`.

**Tests are mandatory** for every new sensor, endpoint, or normalisation change —
use the `mock_coordinator` / `mock_config_entry` fixtures in `tests/conftest.py`.

## Git & releases

- Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`).
- **No AI attribution** anywhere. **No commits unless explicitly asked.**
- Releases: bump `custom_components/waterbeep/manifest.json`, add a `CHANGELOG.md` entry, tag `vX.Y.Z` (the tag must match the manifest version — enforced by `release.yml`).
