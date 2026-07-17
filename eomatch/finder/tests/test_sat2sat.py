"""eomatch.finder.tests.test_sat2sat - tests for eomatch.finder.sat2sat"""

import unittest
import datetime
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

from eomatch.finder.sat2sat import Sat2SatMUFinder
from eomatch.domain import MatchupEvent, Matchup, MatchupSet
import scrappi.product
import scrappi
import orbitx.matchups

__author__ = ""
__all__ = []


class TestSat2SatMUFinder(unittest.TestCase):
    """Unit tests for Sat2SatMUFinder."""

    @classmethod
    def setUpClass(cls):
        base = Path(__file__).parent
        cls.fixture_overlap_2_platforms = base / r"matchup_event_2_platforms.json"
        cls.fixture_overlap_3_platforms = base / r"matchup_event_3_platforms.json"

    # ---------------------------------------------------------------- helpers

    def _make_finder(self, extra_context=None):
        """Create a finder with a minimal context dict.

        All keys read by filter_events and get_orbitx_ds are included with
        defaults so that plain-dict access does not raise KeyError for unset
        settings.
        """
        ctx = {
            "platforms": "S2A,Landsat-9",
            "collections": "S2_MSI_L1C,LANDSAT_C2L1",
            "orbitx_netcdf_path": None,
            "orbitx_netcdf_files": None,
            "propagation_sampling_interval": 30,
            "interpolation_sampling_interval": 5,
            "space_diff_threshold": 280.0,
            "time_diff_threshold": 3600,
            "check_before": True,
            "check_after": True,
            "has_land_ocean_mask": False,
            "custom_satellites": None,
            "dump_orbit": False,
            "min_lat": None,
            "max_lat": None,
            "min_lon": None,
            "max_lon": None,
            "start_time": None,
            "end_time": None,
        }
        if extra_context:
            ctx.update(extra_context)
        return Sat2SatMUFinder(context=ctx)

    def _make_orbitx_event(
        self, lon_min, lat_min, lon_max, lat_max, start="2021-06-01T00:00:00", stop="2021-06-01T01:00:00"
    ):
        """Return a minimal orbitx event dict (format returned by orbitx.matchups.Matchups.events)."""
        return {
            "start_time": np.datetime64(start),
            "stop_time": np.datetime64(stop),
            "bbox": (lon_min, lat_min, lon_max, lat_max),
        }

    def _make_matchup_event_2_platforms(self):
        return MatchupEvent(
            collections=["S2_MSI_L1C", "LANDSAT_C2L1"],
            platforms=["S2A", "Landsat-9"],
            start_time=datetime.datetime(2022, 5, 21, 8),
            stop_time=datetime.datetime(2022, 5, 21, 11),
            latitude_minimum=44.0,
            longitude_minimum=34.0,
            latitude_maximum=46.0,
            longitude_maximum=36.0,
        )

    def _make_matchup_event_3_platforms(self):
        return MatchupEvent(
            collections=["S1_SAR_GRD", "S2_MSI_L1C", "LANDSAT_C2L1"],
            platforms=["S1A", "S2B", "Landsat-8"],
            start_time=datetime.datetime(2022, 6, 1, 9),
            stop_time=datetime.datetime(2022, 6, 1, 11),
            latitude_minimum=10.0,
            longitude_minimum=10.0,
            latitude_maximum=20.0,
            longitude_maximum=20.0,
        )

    @staticmethod
    def _platform_side_effect(all_products):
        """Return a run_scrappi side_effect that filters products by query["platform"]."""
        by_platform = {}
        for p in all_products:
            by_platform.setdefault(p.platform, scrappi.ProductItemSet())
            by_platform[p.platform].add_ProductItem(p)

        def side_effect(query):
            return by_platform.get(query["platform"], scrappi.ProductItemSet())

        return side_effect

    # --------------------------------------------------------- to_matchup_set

    @patch.object(Sat2SatMUFinder, "run_scrappi")
    def test_two_platforms_overlap_and_non_overlap(self, mock_run_scrappi):
        """2 platforms, 6 products total (4 overlapping 2×2, 2 non-overlapping): expect 4 Matchups."""
        all_products = scrappi.product.open_product_item_set(self.fixture_overlap_2_platforms)
        mock_run_scrappi.side_effect = self._platform_side_effect(all_products)

        finder = self._make_finder()
        results = finder.to_matchup_set([self._make_matchup_event_2_platforms()])

        self.assertEqual(len(results), 1)
        mu_event = results[0]
        self.assertIsNotNone(mu_event.matchup_set)
        self.assertIsInstance(mu_event.matchup_set, MatchupSet)
        self.assertEqual(len(mu_event.matchup_set), 4)
        for mu in mu_event.matchup_set:
            self.assertIsInstance(mu, Matchup)
            self.assertEqual(len(mu.products), 2)

    @patch.object(Sat2SatMUFinder, "run_scrappi")
    def test_three_platforms_overlap(self, mock_run_scrappi):
        """3 platforms all overlapping (S1=1, S2=2, L8=1): expect 2 Matchups (1×2×1)."""
        all_products = scrappi.product.open_product_item_set(self.fixture_overlap_3_platforms)
        mock_run_scrappi.side_effect = self._platform_side_effect(all_products)

        finder = self._make_finder()
        results = finder.to_matchup_set([self._make_matchup_event_3_platforms()])

        self.assertEqual(len(results), 1)
        mu_event = results[0]
        self.assertIsNotNone(mu_event.matchup_set)
        self.assertEqual(len(mu_event.matchup_set), 2)
        for mu in mu_event.matchup_set:
            self.assertEqual(len(mu.products), 3)

    @patch.object(Sat2SatMUFinder, "run_scrappi")
    def test_no_products_returns_empty(self, mock_run_scrappi):
        mock_run_scrappi.return_value = scrappi.ProductItemSet()

        finder = self._make_finder()
        results = finder.to_matchup_set([self._make_matchup_event_2_platforms()])

        self.assertEqual(results, [])

    # ---------------------------------------------------------- get_orbitx_ds

    @patch.object(orbitx.matchups.Matchups, "find_matchups")
    def test_get_orbitx_ds_propagator_timedeltas_have_second_units(self, mock_find_matchups):
        """propagation/interpolation/time-diff intervals are passed as second-unit
        np.timedelta64, not unitless — orbitx calls .item().total_seconds() on
        these, which raises AttributeError on a unitless (generic) timedelta64
        since .item() then returns a plain int rather than a datetime.timedelta.
        """
        finder = self._make_finder(
            {
                "start_time": "2021-01-01 00:00:00",
                "end_time": "2021-12-31 23:59:59",
                "propagation_sampling_interval": 30,
                "interpolation_sampling_interval": 5,
                "time_diff_threshold": 3600,
            }
        )
        finder.get_orbitx_ds()

        kwargs = mock_find_matchups.call_args.kwargs
        self.assertEqual(kwargs["propagation_sampling_interval"], np.timedelta64(30, "s"))
        self.assertEqual(kwargs["propagation_sampling_interval"].dtype, np.dtype("timedelta64[s]"))
        self.assertEqual(kwargs["interpolation_sampling_interval"], np.timedelta64(5, "s"))
        self.assertEqual(kwargs["interpolation_sampling_interval"].dtype, np.dtype("timedelta64[s]"))
        self.assertEqual(kwargs["time_diff_threshold"], np.timedelta64(3600, "s"))
        self.assertEqual(kwargs["time_diff_threshold"].dtype, np.dtype("timedelta64[s]"))

    @patch.object(orbitx.matchups.Matchups, "find_matchups")
    def test_get_orbitx_ds_custom_satellites_none_becomes_empty_list(self, mock_find_matchups):
        """custom_satellites=None in config is passed to orbitx as [], not None
        — orbitx iterates over it directly (`for sat_dict in custom_satellites`)
        and raises TypeError on None."""
        finder = self._make_finder(
            {
                "start_time": "2021-01-01 00:00:00",
                "end_time": "2021-12-31 23:59:59",
                "custom_satellites": None,
            }
        )
        finder.get_orbitx_ds()

        kwargs = mock_find_matchups.call_args.kwargs
        self.assertEqual(kwargs["custom_satellites"], [])

    @patch.object(orbitx.matchups.Matchups, "find_matchups")
    def test_get_orbitx_ds_custom_satellites_list_passed_through(self, mock_find_matchups):
        custom_sats = [{"tle_filepath": "sat.tle", "satellite_shortname": "J2", "satellite_name": "Jason-2"}]
        finder = self._make_finder(
            {
                "start_time": "2021-01-01 00:00:00",
                "end_time": "2021-12-31 23:59:59",
                "custom_satellites": custom_sats,
            }
        )
        finder.get_orbitx_ds()

        kwargs = mock_find_matchups.call_args.kwargs
        self.assertEqual(kwargs["custom_satellites"], custom_sats)

    @patch.object(orbitx.matchups.Matchups, "from_netcdf")
    def test_get_orbitx_ds_netcdf_path_year_and_platforms_placeholders(self, mock_from_netcdf):
        """{year} and {platforms} placeholders in orbitx_netcdf_path are substituted
        from start_time and platforms before the file is loaded."""
        mock_ds = MagicMock()
        mock_ds.start_date = np.datetime64("2021-01-01")
        mock_ds.end_date = np.datetime64("2021-12-31")
        mock_from_netcdf.return_value = mock_ds

        finder = self._make_finder(
            {
                "platforms": "S2A,LS9",
                "start_time": "2021-06-01 00:00:00",
                "end_time": "2021-06-30 00:00:00",
                "orbitx_netcdf_path": "/data/{year}/{platforms}.nc",
            }
        )
        result = finder.get_orbitx_ds()

        mock_from_netcdf.assert_called_once_with("/data/2021/S2A_LS9.nc")
        self.assertIs(result, mock_ds)

    # ---------------------------------------------------------- filter_events

    def test_filter_events_empty_data_returns_empty(self):
        """filter_events([]) returns []."""
        self.assertEqual(self._make_finder().filter_events([]), [])

    def test_filter_events_no_spatial_filter_passes_all(self):
        """All events pass when no lat/lon filter is configured."""
        finder = self._make_finder()
        events = [
            self._make_orbitx_event(-180, -90, 180, 90),
            self._make_orbitx_event(0, 0, 10, 10),
        ]
        self.assertEqual(len(finder.filter_events(events)), 2)

    def test_filter_events_lat_bbox_overlapping_range_is_retained(self):
        """Event bbox overlapping the lat filter range is kept."""
        finder = self._make_finder({"min_lat": 23.97, "max_lat": 24.87})
        events = [self._make_orbitx_event(-180, 20, 180, 27)]  # lat 20–27 overlaps 23.97–24.87
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_lat_bbox_entirely_below_is_excluded(self):
        """Event bbox entirely below the lat filter range is excluded."""
        finder = self._make_finder({"min_lat": 23.97, "max_lat": 24.87})
        events = [self._make_orbitx_event(-180, 10, 180, 20)]  # lat 10–20, below 23.97
        self.assertEqual(len(finder.filter_events(events)), 0)

    def test_filter_events_lat_bbox_entirely_above_is_excluded(self):
        """Event bbox entirely above the lat filter range is excluded."""
        finder = self._make_finder({"min_lat": 23.97, "max_lat": 24.87})
        events = [self._make_orbitx_event(-180, 30, 180, 50)]  # lat 30–50, above 24.87
        self.assertEqual(len(finder.filter_events(events)), 0)

    def test_filter_events_lon_bbox_overlapping_range_is_retained(self):
        """Event bbox overlapping the lon filter range is kept."""
        finder = self._make_finder({"min_lon": 12.9, "max_lon": 13.8})
        events = [self._make_orbitx_event(-100, -90, 100, 90)]  # lon -100–100 overlaps 12.9–13.8
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_lon_bbox_entirely_east_is_excluded(self):
        """Event bbox entirely east of the lon filter range is excluded."""
        finder = self._make_finder({"min_lon": 12.9, "max_lon": 13.8})
        events = [self._make_orbitx_event(50, -90, 100, 90)]  # lon 50–100, east of 13.8
        self.assertEqual(len(finder.filter_events(events)), 0)

    def test_filter_events_lon_bbox_entirely_west_is_excluded(self):
        """Event bbox entirely west of the lon filter range is excluded."""
        finder = self._make_finder({"min_lon": 12.9, "max_lon": 13.8})
        events = [self._make_orbitx_event(-50, -90, 10, 90)]  # lon -50–10, west of 12.9
        self.assertEqual(len(finder.filter_events(events)), 0)

    def test_filter_events_wide_swath_intersecting_small_region_is_retained(self):
        """Wide satellite swath bbox intersecting a small filter region is retained.

        Regression test for the centre-point bug: the swath bbox centre lon (0.0)
        lies outside Libya-1's lon filter range (12.9–13.8°E), and centre lat (23.5)
        lies outside the lat range (23.97–24.87°N).  The old centre-point logic
        excluded these events; bbox-intersection logic correctly includes them.
        """
        finder = self._make_finder(
            {
                "min_lat": 23.97,
                "max_lat": 24.87,
                "min_lon": 12.9,
                "max_lon": 13.8,
            }
        )
        # Swath lon -100–100, lat 20–27: centre (0.0, 23.5) is outside filter,
        # but bbox intersects both filter ranges.
        events = [self._make_orbitx_event(-100, 20, 100, 27)]
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_antimeridian_disabled_by_default(self):
        """A wide-bbox event is kept when exclude_antimeridian_events is unset."""
        finder = self._make_finder()
        events = [self._make_orbitx_event(-179, -90, 179, 90)]  # 358 deg span
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_antimeridian_wide_bbox_is_excluded_when_enabled(self):
        """An event bbox spanning more than 180 degrees of longitude (a polar
        crossover artefact) is dropped when exclude_antimeridian_events is set."""
        finder = self._make_finder({"exclude_antimeridian_events": True})
        events = [self._make_orbitx_event(-179, -90, 179, 90)]  # 358 deg span
        self.assertEqual(len(finder.filter_events(events)), 0)

    def test_filter_events_antimeridian_at_threshold_is_retained_when_enabled(self):
        """A bbox spanning exactly 180 degrees is not treated as an antimeridian artefact."""
        finder = self._make_finder({"exclude_antimeridian_events": True})
        events = [self._make_orbitx_event(-90, -10, 90, 10)]  # exactly 180 deg span
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_solar_time_disabled_by_default(self):
        """A night-time event is kept when exclude_night_events is unset, even
        with a lon filter configured."""
        finder = self._make_finder({"min_lon": 12.9, "max_lon": 13.8})
        # UTC 00:00-01:00 is local night-time at ~13 degE (local ~00:53).
        events = [self._make_orbitx_event(12.9, 0, 13.8, 10, start="2021-06-01T00:00:00", stop="2021-06-01T01:00:00")]
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_solar_time_night_event_is_excluded_when_enabled(self):
        """An event entirely within local night-time at the configured site is
        dropped when exclude_night_events is set."""
        finder = self._make_finder({"min_lon": 12.9, "max_lon": 13.8, "exclude_night_events": True})
        # UTC 00:00-01:00 is local night-time at ~13 degE (local ~00:53).
        events = [self._make_orbitx_event(12.9, 0, 13.8, 10, start="2021-06-01T00:00:00", stop="2021-06-01T01:00:00")]
        self.assertEqual(len(finder.filter_events(events)), 0)

    def test_filter_events_solar_time_day_event_is_retained_when_enabled(self):
        """An event within local daytime at the configured site is kept."""
        finder = self._make_finder({"min_lon": 12.9, "max_lon": 13.8, "exclude_night_events": True})
        # UTC 10:00-11:00 is local daytime at ~13 degE (local ~10:53).
        events = [self._make_orbitx_event(12.9, 0, 13.8, 10, start="2021-06-01T10:00:00", stop="2021-06-01T11:00:00")]
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_solar_time_not_applied_without_lon_filter(self):
        """A night-time event is not dropped when no lon filter is configured
        (the site's longitude, needed to compute local solar time, is unknown),
        even when exclude_night_events is set."""
        finder = self._make_finder({"exclude_night_events": True})
        events = [self._make_orbitx_event(-1, 0, 1, 10, start="2021-06-01T00:00:00", stop="2021-06-01T01:00:00")]
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_solar_time_utc_window_wraps_midnight(self):
        """Solar-time UTC window wrap-around branch, for a site far enough west
        that the local-daytime window in UTC straddles 00:00.
        """
        finder = self._make_finder({"min_lon": -171, "max_lon": -169, "exclude_night_events": True})
        # UTC 20:00-21:00 -> local ~08:40-09:40, daytime -> retained.
        day_event = self._make_orbitx_event(-172, 0, -168, 10, start="2021-06-01T20:00:00", stop="2021-06-01T21:00:00")
        # UTC 10:00-11:00 -> local ~22:40-23:40, night-time -> excluded.
        night_event = self._make_orbitx_event(
            -172, 0, -168, 10, start="2021-06-01T10:00:00", stop="2021-06-01T11:00:00"
        )
        self.assertEqual(len(finder.filter_events([day_event])), 1)
        self.assertEqual(len(finder.filter_events([night_event])), 0)

    def test_filter_events_time_straddling_start_is_retained(self):
        """Event whose time window straddles the filter start boundary is kept."""
        finder = self._make_finder({"start_time": "2021-06-01 00:00:00", "end_time": "2021-06-30 00:00:00"})
        events = [self._make_orbitx_event(-180, -90, 180, 90, start="2021-05-31T23:00:00", stop="2021-06-01T01:00:00")]
        self.assertEqual(len(finder.filter_events(events)), 1)

    def test_filter_events_time_entirely_before_is_excluded(self):
        """Event entirely before the filter start is excluded."""
        finder = self._make_finder({"start_time": "2021-06-01 00:00:00", "end_time": "2021-06-30 00:00:00"})
        events = [self._make_orbitx_event(-180, -90, 180, 90, start="2021-05-01T00:00:00", stop="2021-05-31T23:59:59")]
        self.assertEqual(len(finder.filter_events(events)), 0)

    def test_filter_events_time_entirely_after_is_excluded(self):
        """Event entirely after the filter end is excluded."""
        finder = self._make_finder({"start_time": "2021-06-01 00:00:00", "end_time": "2021-06-30 00:00:00"})
        events = [self._make_orbitx_event(-180, -90, 180, 90, start="2021-07-01T00:00:00", stop="2021-07-02T00:00:00")]
        self.assertEqual(len(finder.filter_events(events)), 0)

    def test_filter_events_combined_only_matching_event_retained(self):
        """Only the event satisfying both spatial and time constraints survives."""
        finder = self._make_finder(
            {
                "min_lat": 23.97,
                "max_lat": 24.87,
                "min_lon": 12.9,
                "max_lon": 13.8,
                "start_time": "2021-06-01 00:00:00",
                "end_time": "2021-06-30 00:00:00",
            }
        )
        inside = self._make_orbitx_event(-100, 20, 100, 27, start="2021-06-15T00:00:00", stop="2021-06-15T01:00:00")
        outside_spatial = self._make_orbitx_event(
            50, 50, 100, 80, start="2021-06-15T00:00:00", stop="2021-06-15T01:00:00"
        )
        outside_time = self._make_orbitx_event(
            -100, 20, 100, 27, start="2021-08-01T00:00:00", stop="2021-08-01T01:00:00"
        )

        results = finder.filter_events([inside, outside_spatial, outside_time])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], inside)


if __name__ == "__main__":
    unittest.main()
