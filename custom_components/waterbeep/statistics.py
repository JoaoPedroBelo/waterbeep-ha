"""Import Waterbeep daily consumption as long-term external statistics.

Waterbeep readings are **backdated**: yesterday's total is only known today. A
live ``total_increasing`` sensor can therefore only ever say "the running total
went up *now*", so the Energy/Water dashboard — which derives consumption from
the sensor's hourly deltas — attributes every day's usage to the poll hour and
scrambles the daily distribution.

Instead we import each completed day directly as an hourly external statistic
timestamped at that day's **local midnight**. The Energy dashboard then shows the
same day-by-day bars as the official Waterbeep dashboard, history included, with
no install-time spike (each day lands in its own bucket).

Because we re-poll a sliding 30-day window, the running ``sum`` is continued from
the last statistic already stored (queried via ``get_last_statistics``) and only
days newer than that are appended — keeping ``sum`` monotonic and never
re-writing history.
"""

from __future__ import annotations

from datetime import date
import logging
from typing import Any, Final

from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# External statistic id (``<domain>:<object_id>``) surfaced to the Energy
# dashboard's water source. External ids use a colon, not a dot.
STATISTIC_ID: Final = f"{DOMAIN}:consumption"
STATISTIC_NAME: Final = "Waterbeep Consumption"

# Waterbeep posts a day's total with a delay — a day can read 0 for a while
# after it closes, then fill in. So we don't lock a day in on first sight;
# instead each poll re-imports a trailing window of recent days (overwriting any
# late-arriving corrections), anchored on the cumulative sum of the last stable
# day before the window. Older history is never rewritten.
CORRECTION_DAYS: Final = 7


def build_statistic_points(
    series: list[dict[str, Any]],
    last_iso: str | None,
    last_sum: float,
    today_iso: str,
) -> list[dict[str, Any]]:
    """Return ``[{"iso", "state", "sum"}]`` for complete days newer than last_iso.

    The still-open current day (``iso >= today_iso``) and days already imported
    (``iso <= last_iso``) are skipped, and a monotonic running ``sum`` is carried
    forward so the Energy dashboard's period diff (``sum[day] - sum[day-1]``)
    yields exactly that day's m³.
    """
    running = last_sum
    points: list[dict[str, Any]] = []
    for entry in sorted(series, key=lambda e: e["iso"]):
        iso = entry["iso"]
        if iso >= today_iso:
            continue
        if last_iso is not None and iso <= last_iso:
            continue
        running = round(running + entry["value"], 3)
        points.append({"iso": iso, "state": entry["value"], "sum": running})
    return points


async def async_import_consumption_statistics(
    hass: HomeAssistant,
    series: list[dict[str, Any]],
    today_iso: str,
) -> None:
    """Import completed days into the ``waterbeep:consumption`` statistic.

    Re-imports a trailing window of recent days each call so Waterbeep's
    late-arriving daily totals overwrite any earlier (0) values, then extends
    with newly completed days.
    """
    # The recorder is a declared dependency but must be imported lazily: the
    # module pulls in native deps that are intentionally absent from the unit
    # test environment (see tests/test_statistics.py, which covers the pure
    # ``build_statistic_points`` decision logic instead).
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
        get_last_statistics,
    )

    if not series:
        return

    # Anchor on the last *stable* day: fetch the most recent stored days and step
    # back CORRECTION_DAYS. Everything after the anchor is recomputed from the
    # current series and re-imported, so late-arriving values overwrite whatever
    # (possibly 0) was stored earlier; the anchor's cumulative sum keeps the
    # series monotonic across the overwrite and across month boundaries.
    last_stats = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, CORRECTION_DAYS + 1, STATISTIC_ID, True, {"sum"}
    )
    stored = sorted(
        last_stats.get(STATISTIC_ID) or [], key=lambda r: float(r["start"])
    )
    if stored:
        anchor = stored[0]
        anchor_sum = float(anchor.get("sum") or 0.0)
        anchor_iso: str | None = _ts_to_local_iso(float(anchor["start"]))
    else:
        anchor_sum = 0.0
        anchor_iso = None

    points = build_statistic_points(series, anchor_iso, anchor_sum, today_iso)
    if not points:
        return

    statistics: list[StatisticData] = [
        {
            "start": dt_util.start_of_local_day(date.fromisoformat(p["iso"])),
            "state": p["state"],
            "sum": p["sum"],
        }
        for p in points
    ]
    metadata: StatisticMetaData = {
        "has_mean": False,
        "has_sum": True,
        "name": STATISTIC_NAME,
        "source": DOMAIN,
        "statistic_id": STATISTIC_ID,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
    }
    async_add_external_statistics(hass, metadata, statistics)
    _LOGGER.debug(
        "Imported %d Waterbeep consumption statistic(s) up to %s",
        len(points),
        points[-1]["iso"],
    )


def _ts_to_local_iso(start_ts: float) -> str:
    """Convert a recorder ``start`` timestamp to a local ``YYYY-MM-DD`` date.

    ``get_last_statistics`` returns ``start`` as epoch seconds, but some HA
    versions have used milliseconds; normalise defensively (a 2020+ date is
    ~1.6e9 s vs ~1.6e12 ms, so the split is unambiguous).
    """
    if start_ts > 1e11:
        start_ts /= 1000.0
    local = dt_util.utc_from_timestamp(start_ts).astimezone(dt_util.DEFAULT_TIME_ZONE)
    return local.date().isoformat()
