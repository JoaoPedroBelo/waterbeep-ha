"""Constants for the Waterbeep integration."""

from typing import Final

DOMAIN: Final = "waterbeep"

# Configuration keys
# NOTE: The auth model is provisional until the Waterbeep API requests are
# captured. Adjust these once the real login/token flow is known (see docs/API.md).
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_METER_ID: Final = "meter_id"

# --- Automatic two-factor code retrieval (optional, opt-in) ---
# Waterbeep can deliver its one-time code by email. When the user forwards that
# mail to a Resend inbound address, the integration reads the code back through
# Resend's "Received emails" API and clears the challenge unattended. An empty
# API key disables the whole feature (the manual OTP prompt still works).
CONF_OTP_RESEND_API_KEY: Final = "otp_resend_api_key"
# Optional narrowing filters, matched as case-insensitive substrings against the
# inbound mail's ``from`` / ``to``. Empty means "accept any", which is right when
# the Resend inbox is dedicated to this integration.
CONF_OTP_FROM_FILTER: Final = "otp_from_filter"
CONF_OTP_TO_FILTER: Final = "otp_to_filter"

# Resend "Received emails" API (bearer-authenticated, GET only).
RESEND_API_BASE: Final = "https://api.resend.com"
RESEND_RECEIVING_PATH: Final = "/emails/receiving"
RESEND_LIST_LIMIT: Final = 20  # Resend caps ``limit`` at 100

# How long to wait for the forwarded code mail to land in the Resend inbox.
# Mail forwarding adds seconds-to-a-minute of latency, so this is generous.
OTP_WAIT_TIMEOUT: Final = 180  # seconds
OTP_POLL_INTERVAL: Final = 5  # seconds between Resend polls
# Leeway when matching a mail's ``created_at`` against the moment we asked
# Waterbeep for the code, to absorb clock skew between HA and Resend.
OTP_CLOCK_SKEW: Final = 60  # seconds
OTP_CODE_LENGTH: Final = 6

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
