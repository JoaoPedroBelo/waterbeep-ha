# Architecture

Waterbeep is a **cloud polling** integration. Home Assistant periodically logs
into the Aquamatrix Waterbeep web app and reads the dashboard endpoints.

## Data flow

```
DataUpdateCoordinator (coordinator.py)
        │  every scan_interval (default 1h)
        ▼
WaterbeepClient.async_get_data()  (api.py)
        │  login (if needed) → GET dashboard → POST AJAX endpoints
        ▼
raw JSON  ──►  coordinator._normalise()  ──►  self.data (flat dict)
                                                    │
                                                    ▼
                        CoordinatorEntity sensors / binary_sensors
```

## Components

| File | Purpose |
|------|---------|
| `api.py` | HTTP client: session, antiforgery handling, login, endpoint calls. **All network logic lives here.** |
| `coordinator.py` | `DataUpdateCoordinator`; normalises raw API payloads into `self.data`. |
| `const.py` | `Final`-typed constants: config keys, entity suffixes, `coordinator.data` keys. |
| `config_flow.py` / `__init__.py` | Setup UI (validated by a live login) / entry point. |
| `sensor.py` / `binary_sensor.py` | Entities. All state read from `coordinator.data`; return `None` when missing. |

## Rules

1. **All network logic in `api.py`.** The coordinator never talks HTTP directly.
2. **All state in the coordinator.** Entities only read `self.coordinator.data.get(...)`.
3. **The client owns its own cookie jar** — never the shared HA session — so the
   authenticated session is isolated.
4. **Log via `_LOGGER`**, never `print()`.
5. Re-login transparently once on an auth error, then fail the update.
