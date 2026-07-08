"""Data update coordinator for the Waterbeep integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    WaterbeepAuthError,
    WaterbeepClient,
    WaterbeepError,
    WaterbeepTwoFactorRequired,
)
from .const import (
    CONF_METER_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_AVAILABLE,
    DATA_CAPITATION_AVG,
    DATA_CONSUMPTION_7D,
    DATA_CONSUMPTION_30D,
    DATA_CONSUMPTION_DAY,
    DATA_DAILY_LABELS,
    DATA_DAILY_SERIES,
    DATA_DAILY_VALUES,
    DATA_MONTH_LABEL,
    DATA_MONTH_LABELS,
    DATA_MONTH_LATEST,
    DATA_MONTH_VALUES,
    DEFAULT_INHABITANTS,
    DOMAIN,
    POLL_HOURS,
    POLL_MINUTE,
)

_LOGGER = logging.getLogger(__name__)


class WaterbeepCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the Waterbeep service and expose normalised data to entities.

    All entity state lives here in ``self.data``; entities only ever read
    ``self.data.get(...)`` and return ``None`` for missing values.
    """

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        """Initialise the coordinator from the merged config entry data."""
        self._user_code = config[CONF_USERNAME]
        self.meter_id: str | None = config.get(CONF_METER_ID)

        self.client = WaterbeepClient(
            user_code=self._user_code,
            password=config[CONF_PASSWORD],
            inhabitants=DEFAULT_INHABITANTS,
        )
        self._unsub_schedule: list[CALLBACK_TYPE] = []

        # No periodic ``update_interval``: we poll on a fixed twice-daily
        # schedule instead (see ``async_setup_schedule``) to stay low-profile.
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )

    @callback
    def async_setup_schedule(self) -> None:
        """Register fixed twice-daily refreshes at 01:00 and 13:00 local time.

        Returns nothing; the caller stores the unsubscribe callback via
        ``entry.async_on_unload``.
        """

        async def _scheduled_refresh(_now: Any) -> None:
            await self.async_request_refresh()

        for hour in POLL_HOURS:
            unsub = async_track_time_change(
                self.hass,
                _scheduled_refresh,
                hour=hour,
                minute=POLL_MINUTE,
                second=0,
            )
            self._unsub_schedule.append(unsub)

    def async_teardown_schedule(self) -> None:
        """Cancel all scheduled refreshes."""
        while self._unsub_schedule:
            self._unsub_schedule.pop()()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and normalise the latest data from Waterbeep."""
        try:
            raw = await self.client.async_get_data()
        except WaterbeepTwoFactorRequired as err:
            # Waterbeep is challenging with 2FA; trigger HA's reauth flow so the
            # user can complete the one-time code and re-trust this connection.
            raise ConfigEntryAuthFailed(
                "Waterbeep requires two-factor verification"
            ) from err
        except WaterbeepAuthError as err:
            # Auth errors are not transient - surface as a reauth so HA prompts
            # the user rather than retrying forever.
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except WaterbeepError as err:
            raise UpdateFailed(f"Error communicating with Waterbeep: {err}") from err

        return self._normalise(raw, dt_util.now().date().isoformat())

    @staticmethod
    def _normalise(raw: dict[str, Any], today_iso: str) -> dict[str, Any]:
        """Map the four dashboard payloads into flat coordinator data.

        Chart shape (verified live)::

            {"succeed": true, "data": {
                "labels": ["2 Jul 2026", ...], "days": [...],
                "years": [...], "months": [...],
                "values": [0.231, ...],              # m³/day (daily) or m³ (monthly)
                "averageDailyConsumption": 0.12}}

        ``today_iso`` (``YYYY-MM-DD``) marks the still-incomplete current day so
        the "latest complete day" sensor ignores it.
        """
        data: dict[str, Any] = {DATA_AVAILABLE: True}

        # --- 30-day daily series (drives the cumulative accumulator) ---
        thirty = _chart_data(raw.get("thirty_days"))
        if thirty:
            values = _to_floats(thirty.get("values"))
            labels = thirty.get("labels")
            series = _daily_series(thirty)
            if isinstance(labels, list):
                data[DATA_DAILY_LABELS] = labels
            if values:
                data[DATA_DAILY_VALUES] = values
                data[DATA_CONSUMPTION_30D] = round(sum(values), 3)
            if series:
                data[DATA_DAILY_SERIES] = series
                complete = [e["value"] for e in series if e["iso"] < today_iso]
                if complete:
                    data[DATA_CONSUMPTION_DAY] = complete[-1]

        # --- 7-day total ---
        seven = _chart_data(raw.get("seven_days"))
        if seven:
            week = _to_floats(seven.get("values"))
            if week:
                data[DATA_CONSUMPTION_7D] = round(sum(week), 3)

        # --- monthly billed consumption (m³) ---
        monthly = _chart_data(raw.get("monthly"))
        if monthly:
            m_values = _to_floats(monthly.get("values"))
            m_labels = monthly.get("labels")
            if isinstance(m_labels, list):
                data[DATA_MONTH_LABELS] = m_labels
            if m_values:
                data[DATA_MONTH_VALUES] = m_values
                data[DATA_MONTH_LATEST] = m_values[-1]
                if isinstance(m_labels, list) and m_labels:
                    data[DATA_MONTH_LABEL] = m_labels[-1]

        # --- per-capita average (L/person/day) ---
        capitation = _chart_data(raw.get("capitation"))
        if capitation:
            avg = capitation.get("averageDailyConsumption")
            if isinstance(avg, (int, float)):
                data[DATA_CAPITATION_AVG] = round(float(avg), 2)

        return data


def _chart_data(chart: Any) -> dict[str, Any] | None:
    """Return the inner ``data`` dict of a chart payload if it succeeded."""
    if (
        isinstance(chart, dict)
        and chart.get("succeed")
        and isinstance(chart.get("data"), dict)
    ):
        return chart["data"]
    return None


def _daily_series(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ``[{"iso": "YYYY-MM-DD", "value": m³}]`` from a daily chart.

    Requires aligned ``years``/``months``/``days``/``values`` arrays.
    """
    years = payload.get("years")
    months = payload.get("months")
    days = payload.get("days")
    values = _to_floats(payload.get("values"))
    if not all(isinstance(x, list) for x in (years, months, days)):
        return []
    n = min(len(years), len(months), len(days), len(values))
    series: list[dict[str, Any]] = []
    for i in range(n):
        try:
            iso = f"{int(years[i]):04d}-{int(months[i]):02d}-{int(days[i]):02d}"
        except (TypeError, ValueError):
            continue
        series.append({"iso": iso, "value": values[i]})
    return series


def _to_floats(raw: Any) -> list[float]:
    """Coerce a list into floats, dropping anything non-numeric."""
    if not isinstance(raw, list):
        return []
    result: list[float] = []
    for item in raw:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            continue
    return result


def accumulate_total(
    prev_total: float,
    last_iso: str | None,
    series: list[dict[str, Any]],
    today_iso: str,
) -> tuple[float, str | None]:
    """Add each complete day not yet counted to a monotonic running total.

    Days on or after ``today_iso`` are skipped (still changing); days already
    counted (``iso <= last_iso``) are skipped. Returns ``(new_total, new_last_iso)``.
    The total only ever increases, satisfying the Energy dashboard's
    ``total_increasing`` contract.
    """
    total = prev_total
    newest = last_iso
    for entry in sorted(series, key=lambda e: e["iso"]):
        iso = entry["iso"]
        if iso >= today_iso:
            continue
        if last_iso is not None and iso <= last_iso:
            continue
        total += entry["value"]
        if newest is None or iso > newest:
            newest = iso
    return round(total, 3), newest
