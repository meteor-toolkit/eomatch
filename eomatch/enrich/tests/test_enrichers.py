"""eomatch.tests.test_enrichers — unit tests for built-in enricher functions."""

import datetime as dt
import unittest

from shapely.geometry import Polygon

# ---------------------------------------------------------------------------
# Minimal Matchup stand-in — enrichers only access the domain interface,
# not internal product details, so a lightweight duck-type is sufficient.
# ---------------------------------------------------------------------------


class _FakeMatchup:
    def __init__(self, region: Polygon, t0: dt.datetime, t1: dt.datetime) -> None:
        self._region = region
        self._t0 = t0
        self._t1 = t1

    @property
    def collocation_region(self) -> Polygon:
        return self._region

    @property
    def product_time_bounds(self):
        return min(self._t0, self._t1), max(self._t0, self._t1)

    def time_diff(self) -> float:
        return (self._t1 - self._t0).total_seconds()


# Small ocean region (South Atlantic — should be almost entirely ocean)
OCEAN_REGION = Polygon([(-30, -40), (-30, -35), (-25, -35), (-25, -40), (-30, -40)])

# Small region over central Europe — should be mostly land
LAND_REGION = Polygon([(8, 47), (8, 50), (14, 50), (14, 47), (8, 47)])

T0 = dt.datetime(2022, 5, 21, 8, 40, 0, tzinfo=dt.timezone.utc)
T1 = dt.datetime(2022, 5, 21, 8, 45, 30, tzinfo=dt.timezone.utc)  # 330 s after T0


class TestTimeDiff(unittest.TestCase):
    def setUp(self):
        from eomatch.enrich.time_diff import time_diff

        self.enricher = time_diff
        self.region = OCEAN_REGION

    def test_returns_time_diff_s_key(self):
        mu = _FakeMatchup(self.region, T0, T1)
        result = self.enricher(mu)
        self.assertIn("time_diff_s", result)

    def test_positive_when_t1_after_t0(self):
        mu = _FakeMatchup(self.region, T0, T1)
        self.assertAlmostEqual(self.enricher(mu)["time_diff_s"], 330.0)

    def test_negative_when_t1_before_t0(self):
        mu = _FakeMatchup(self.region, T1, T0)  # swapped
        self.assertAlmostEqual(self.enricher(mu)["time_diff_s"], -330.0)

    def test_zero_when_simultaneous(self):
        mu = _FakeMatchup(self.region, T0, T0)
        self.assertEqual(self.enricher(mu)["time_diff_s"], 0.0)


class TestGeometric(unittest.TestCase):
    def setUp(self):
        from eomatch.enrich.geometric import geometric

        self.enricher = geometric
        self.mu = _FakeMatchup(OCEAN_REGION, T0, T1)

    def test_returns_expected_keys(self):
        result = self.enricher(self.mu)
        self.assertIn("collocation_area_km2", result)
        self.assertIn("collocation_centroid_lon", result)
        self.assertIn("collocation_centroid_lat", result)

    def test_area_is_positive(self):
        self.assertGreater(self.enricher(self.mu)["collocation_area_km2"], 0)

    def test_centroid_within_region_bounds(self):
        result = self.enricher(self.mu)
        minx, miny, maxx, maxy = OCEAN_REGION.bounds
        self.assertGreaterEqual(result["collocation_centroid_lon"], minx)
        self.assertLessEqual(result["collocation_centroid_lon"], maxx)
        self.assertGreaterEqual(result["collocation_centroid_lat"], miny)
        self.assertLessEqual(result["collocation_centroid_lat"], maxy)

    def test_centroid_is_region_centroid(self):
        result = self.enricher(self.mu)
        expected = OCEAN_REGION.centroid
        self.assertAlmostEqual(result["collocation_centroid_lon"], expected.x, places=4)
        self.assertAlmostEqual(result["collocation_centroid_lat"], expected.y, places=4)

    def test_area_roughly_correct_for_known_region(self):
        # OCEAN_REGION is a ~5° × 5° box near 37.5°S.  At that latitude
        # 1° lon ≈ 88 km and 1° lat ≈ 111 km → roughly 5*88 × 5*111 ≈ 244k km².
        # Allow a wide tolerance for the low-res approximation.
        area = self.enricher(self.mu)["collocation_area_km2"]
        self.assertGreater(area, 100_000)
        self.assertLess(area, 350_000)


class TestSolarElevation(unittest.TestCase):
    def setUp(self):
        import importlib.util

        if importlib.util.find_spec("pysolar") is None:
            self.skipTest("pysolar not installed")
        from eomatch.enrich.solar_elevation import solar_elevation

        self.enricher = solar_elevation
        # Mid-morning overpass over Europe — should be daytime
        self.mu_day = _FakeMatchup(
            LAND_REGION,
            dt.datetime(2022, 6, 15, 9, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2022, 6, 15, 9, 0, 30, tzinfo=dt.timezone.utc),
        )
        # Midnight overpass — should be night-time
        self.mu_night = _FakeMatchup(
            LAND_REGION,
            dt.datetime(2022, 6, 15, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2022, 6, 15, 0, 0, 30, tzinfo=dt.timezone.utc),
        )

    def test_returns_solar_elevation_deg_key(self):
        result = self.enricher(self.mu_day)
        self.assertIn("solar_elevation_deg", result)

    def test_daytime_elevation_positive(self):
        result = self.enricher(self.mu_day)
        self.assertGreater(result["solar_elevation_deg"], 0)

    def test_nighttime_elevation_negative(self):
        result = self.enricher(self.mu_night)
        self.assertLess(result["solar_elevation_deg"], 0)

    def test_naive_datetime_handled(self):
        # Matchup with naive (tz-unaware) datetimes should not raise.
        mu = _FakeMatchup(
            LAND_REGION,
            dt.datetime(2022, 6, 15, 9, 0, 0),
            dt.datetime(2022, 6, 15, 9, 0, 30),
        )
        result = self.enricher(mu)
        self.assertIn("solar_elevation_deg", result)


class TestLandFraction(unittest.TestCase):
    def setUp(self):
        import importlib.util

        if importlib.util.find_spec("geopandas") is None:
            self.skipTest("geopandas not installed")
        from eomatch.enrich.land_fraction import land_fraction

        self.enricher = land_fraction

    def test_returns_land_fraction_key(self):
        mu = _FakeMatchup(OCEAN_REGION, T0, T1)
        result = self.enricher(mu)
        self.assertIn("land_fraction", result)

    def test_value_between_zero_and_one(self):
        for region in (OCEAN_REGION, LAND_REGION):
            mu = _FakeMatchup(region, T0, T1)
            val = self.enricher(mu)["land_fraction"]
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)

    def test_ocean_region_near_zero(self):
        mu = _FakeMatchup(OCEAN_REGION, T0, T1)
        val = self.enricher(mu)["land_fraction"]
        self.assertLess(val, 0.1, "South Atlantic region should be mostly ocean")

    def test_land_region_near_one(self):
        mu = _FakeMatchup(LAND_REGION, T0, T1)
        val = self.enricher(mu)["land_fraction"]
        self.assertGreater(val, 0.9, "Central Europe region should be mostly land")

    def test_zero_area_region_returns_zero(self):
        # A degenerate region (zero area) should not raise and return 0.0.
        from shapely.geometry import Point

        zero_region = Point(0, 0).buffer(0)

        class _ZeroMatchup(_FakeMatchup):
            @property
            def collocation_region(self):
                return zero_region

        mu = _ZeroMatchup(zero_region, T0, T1)
        result = self.enricher(mu)
        self.assertEqual(result["land_fraction"], 0.0)


if __name__ == "__main__":
    unittest.main()
