"""Constants for the Waterbeep integration."""

from typing import Final

DOMAIN: Final = "waterbeep"

# Configuration keys
# NOTE: The auth model is provisional until the Waterbeep API requests are
# captured. Adjust these once the real login/token flow is known (see docs/API.md).
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_METER_ID: Final = "meter_id"

# Polling schedule.
# Waterbeep readings arrive daily / in 15-min blocks for the previous day, so
# there is no value in frequent polling. We deliberately hit the service only
# twice a day (01:00 and 13:00, local time) to stay low-profile against their
# servers rather than running a tight periodic loop.
POLL_HOURS: Final = (1, 13)
POLL_MINUTE: Final = 0

# Waterbeep cloud endpoint (verified live)
BASE_URL: Final = "https://www.aquamatrix.pt"

# Dashboard AJAX endpoints (verified live; all POST, token in body except noted)
EP_SEVEN_DAYS: Final = "Dashboard/GetLastSevenDaysChart"
EP_THIRTY_DAYS: Final = "Dashboard/GetLastThirtyDaysChart"
EP_MONTHLY: Final = "Dashboard/GetLastConsumptionReadingsChart"
EP_CAPITATION: Final = "Dashboard/GetCapitationConsumption"  # body: numberOfInhabitants

# Entity unique ID suffixes.
# Daily/monthly consumption values are in cubic metres (m³); capitation is
# litres per person per day. The Energy/Water dashboard is driven by the
# ``waterbeep:consumption`` long-term statistic (see statistics.py), not a sensor.
SENSOR_CONSUMPTION_DAY: Final = "consumption_day"  # latest complete day (m³)
SENSOR_CONSUMPTION_7D: Final = "consumption_7d"  # last 7 days total (m³)
SENSOR_CONSUMPTION_30D: Final = "consumption_30d"  # last 30 days total (m³)
SENSOR_MONTH: Final = "consumption_month"  # latest full billed month (m³)
SENSOR_CAPITATION: Final = "capitation"  # per-capita average (L/person/day)

BINARY_SENSOR_AVAILABLE: Final = "available"  # service reachable

# coordinator.data keys
DATA_AVAILABLE: Final = "available"
DATA_DAILY_SERIES: Final = "daily_series"  # [{"iso": "2026-07-02", "value": m³}]
DATA_DAILY_LABELS: Final = "daily_labels"  # 30-day date labels
DATA_DAILY_VALUES: Final = "daily_values"  # 30-day m³ values
DATA_CONSUMPTION_DAY: Final = "consumption_day"  # latest complete day (m³)
DATA_CONSUMPTION_7D: Final = "consumption_7d"  # last 7 days total (m³)
DATA_CONSUMPTION_30D: Final = "consumption_30d"  # last 30 days total (m³)
DATA_MONTH_LATEST: Final = "month_latest"  # latest billed month (m³)
DATA_MONTH_LABEL: Final = "month_label"  # label of latest billed month
DATA_MONTH_VALUES: Final = "month_values"  # monthly m³ series
DATA_MONTH_LABELS: Final = "month_labels"  # monthly labels
DATA_CAPITATION_AVG: Final = "capitation_avg"  # per-capita avg (L/person/day)

# Number of inhabitants used for the capitation query (fixed for now).
DEFAULT_INHABITANTS: Final = 2

# Attributes
ATTR_METER_ID: Final = "meter_id"
ATTR_LABELS: Final = "labels"
ATTR_VALUES: Final = "values"
