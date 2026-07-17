"""Tests for the Waterbeep external-statistics importer.

Only the pure ``build_statistic_points`` decision logic is unit-tested; the thin
recorder glue (``async_import_consumption_statistics``) pulls in native recorder
deps that are intentionally absent from the test environment.
"""

from custom_components.waterbeep.statistics import STATISTIC_ID, build_statistic_points

# Real-shaped daily series (oldest -> newest), m³ per day.
SERIES = [
    {"iso": "2026-07-02", "value": 0.231},
    {"iso": "2026-07-03", "value": 0.592},
    {"iso": "2026-07-04", "value": 0.032},
    {"iso": "2026-07-05", "value": 0.005},
]


def test_statistic_id_is_external():
    # External statistic ids are ``<domain>:<object_id>`` (colon, not dot).
    assert STATISTIC_ID == "waterbeep:consumption"


class TestBuildStatisticPoints:
    """`build_statistic_points` accumulates a monotonic, non-duplicating sum."""

    def test_fresh_import_takes_all_complete_days(self):
        # today = 5 Jul -> import 2,3,4 (5 still open); sum runs cumulatively.
        points = build_statistic_points(SERIES, None, 0.0, "2026-07-05")
        assert [p["iso"] for p in points] == [
            "2026-07-02",
            "2026-07-03",
            "2026-07-04",
        ]
        assert [p["state"] for p in points] == [0.231, 0.592, 0.032]
        assert [p["sum"] for p in points] == [0.231, 0.823, 0.855]

    def test_open_current_day_is_skipped(self):
        points = build_statistic_points(SERIES, None, 0.0, "2026-07-04")
        assert [p["iso"] for p in points] == ["2026-07-02", "2026-07-03"]

    def test_incremental_appends_only_new_days_continuing_sum(self):
        # Already imported through 4 Jul at cumulative sum 0.855.
        points = build_statistic_points(SERIES, "2026-07-04", 0.855, "2026-07-06")
        assert len(points) == 1
        assert points[0]["iso"] == "2026-07-05"
        assert points[0]["state"] == 0.005
        assert points[0]["sum"] == 0.86  # 0.855 + 0.005

    def test_idempotent_when_no_new_days(self):
        points = build_statistic_points(SERIES, "2026-07-04", 0.855, "2026-07-05")
        assert points == []

    def test_sum_continues_from_existing_baseline(self):
        # A non-zero prior sum (history already in the recorder) is carried on.
        points = build_statistic_points(SERIES, "2026-07-03", 100.0, "2026-07-06")
        assert [p["iso"] for p in points] == ["2026-07-04", "2026-07-05"]
        assert [p["sum"] for p in points] == [100.032, 100.037]

    def test_unsorted_input_is_ordered(self):
        shuffled = [SERIES[2], SERIES[0], SERIES[3], SERIES[1]]
        points = build_statistic_points(shuffled, None, 0.0, "2026-07-06")
        assert [p["iso"] for p in points] == [
            "2026-07-02",
            "2026-07-03",
            "2026-07-04",
            "2026-07-05",
        ]

    def test_empty_series(self):
        assert build_statistic_points([], None, 0.0, "2026-07-06") == []

    def test_reimport_from_anchor_corrects_a_late_value(self):
        # A day previously stored as 0 (late Waterbeep posting) now has its real
        # value. Re-importing from the stable anchor (2 Jul, sum 0.231) recomputes
        # the trailing days from current values, overwriting the stale 0.
        series = [
            {"iso": "2026-07-02", "value": 0.231},  # anchor day (stable)
            {"iso": "2026-07-03", "value": 0.592},  # was 0 before, now filled in
            {"iso": "2026-07-04", "value": 0.032},
        ]
        points = build_statistic_points(series, "2026-07-02", 0.231, "2026-07-05")
        assert [p["iso"] for p in points] == ["2026-07-03", "2026-07-04"]
        assert [p["state"] for p in points] == [0.592, 0.032]
        assert [p["sum"] for p in points] == [0.823, 0.855]
