# Architecture

Waterbeep is a **cloud polling** integration. Home Assistant logs into the
Aquamatrix Waterbeep web app twice a day and reads the dashboard endpoints the
browser uses. There is no public API — HA acts as a browser client.

## Component overview

```mermaid
graph TD
    subgraph HA["Home Assistant"]
        CF["config_flow.py<br/>(live-login validation)"]
        INIT["__init__.py<br/>(entry setup / unload)"]
        COORD["coordinator.py<br/>WaterbeepCoordinator<br/>normalises → self.data"]
        SENS["sensor.py<br/>6 sensors"]
        BIN["binary_sensor.py<br/>availability"]
    end
    API["api.py<br/>WaterbeepClient<br/>(all HTTP + auth)"]
    WB["Aquamatrix SMSnet<br/>(ASP.NET Core)<br/>aquamatrix.pt/waterbeep"]

    CF -->|validate credentials| API
    INIT -->|create + schedule| COORD
    COORD -->|async_get_data| API
    API -->|HTTPS + private cookie jar| WB
    SENS -->|read self.data.get| COORD
    BIN -->|read self.data.get| COORD
```

## Data flow

```mermaid
sequenceDiagram
    autonumber
    participant T as async_track_time_change<br/>(01:00 / 13:00)
    participant C as WaterbeepCoordinator
    participant A as WaterbeepClient (api.py)
    participant W as Waterbeep backend
    participant E as Sensors / binary_sensor

    T->>C: async_request_refresh()
    C->>A: async_get_data()
    alt not logged in / session expired
        A->>W: login (GET + POST /Account/Login)
        W-->>A: auth cookie + antiforgery token
    end
    A->>W: POST Dashboard/Get* (token in body)
    W-->>A: raw JSON (4 charts)
    A-->>C: raw dict
    C->>C: _normalise() → flat self.data
    C-->>E: notify listeners
    E->>C: read self.coordinator.data.get(...)
```

## Components

| File | Purpose |
|------|---------|
| `api.py` | HTTP client: private session, antiforgery handling, login, endpoint calls. **All network logic lives here.** |
| `coordinator.py` | `DataUpdateCoordinator`; normalises the four raw payloads into a flat `self.data`, and provides `accumulate_total` for the cumulative sensor. |
| `const.py` | `Final`-typed constants: config keys, endpoints, entity suffixes, `coordinator.data` keys, `POLL_HOURS`. |
| `config_flow.py` / `__init__.py` | Setup UI (validated by a live login) / entry point (registers the twice-daily schedule). |
| `sensor.py` / `binary_sensor.py` | Entities. All state read from `coordinator.data`; return `None` when missing. |

## Sensors

| Entity | `coordinator.data` key | Unit | State class |
|--------|------------------------|------|-------------|
| Total Consumption | `daily_series` (accumulated) | m³ | `total_increasing` |
| Daily Consumption | `consumption_day` | m³ | `measurement` |
| 7-Day Consumption | `consumption_7d` | m³ | `measurement` |
| 30-Day Consumption | `consumption_30d` | m³ | `measurement` |
| Last Month Consumption | `month_latest` | m³ | `measurement` |
| Average Per-Capita Consumption | `capitation_avg` | L | `measurement` |
| Available (binary) | `available` | — | — |

The **Total Consumption** sensor is the Energy/Water dashboard entity. The
Waterbeep API exposes no lifetime meter index, so it synthesises a monotonic
value with `accumulate_total`, adding each newly completed day exactly once and
persisting the running total plus a date cursor across restarts (see
[`API.md`](API.md)).

## Polling schedule

```mermaid
timeline
    title Twice-daily poll (local time)
    01:00 : refresh
    13:00 : refresh
```

`update_interval` is `None` — there is no tight periodic loop. Instead the
coordinator registers two fixed daily refreshes via `async_track_time_change`
at the hours in `POLL_HOURS` (`01:00` / `13:00`) to stay low-profile against
Waterbeep's servers. Readings arrive daily for the previous day, so more
frequent polling would add no value.

## Rules

1. **All network logic in `api.py`.** The coordinator never talks HTTP directly.
2. **All state in the coordinator.** Entities only read `self.coordinator.data.get(...)`.
3. **The client owns its own cookie jar** — never the shared HA session — so the
   authenticated session is isolated.
4. **Poll twice a day** (`01:00` / `13:00`) via `async_track_time_change`.
5. **Log via `_LOGGER`**, never `print()`.
6. Re-login transparently once on an auth error, then fail the update.
