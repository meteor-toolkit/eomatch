"""eomatch.finder.tests.test_sat2sat - tests for eomatch.finder.sat2sat"""

import unittest

from eomatch.finder.sat2sat import Sat2SatMUFinder
from eomatch.domain import MatchupEvent


__author__ = ""
__all__ = []


import datetime
from pathlib import Path
from unittest.mock import patch

from eomatch.domain import Matchup, MatchupSet
import scrappi.product


class TestSat2SatMUFinder(unittest.TestCase):
    """
    Unit tests for Sat2SatMUFinder.to_matchup_set
    """

    @classmethod
    def setUpClass(cls):
        """
        Paths to prepared Scrappi JSON fixtures
        """
        base = Path(__file__).parent

        cls.fixture_overlap_2_platforms = base / r"matchup_event_2_platforms.json"
        cls.fixture_overlap_3_platforms = base / r"matchup_event_3_platforms.json"

    def _make_finder(self):
        """
        Create a finder with minimal context
        """
        finder = Sat2SatMUFinder(
            context={
                "platforms": "S2A,Landsat-9",
                "orbitx_netcdf_path": None,
            }
        )
        return finder

    def _make_event_2_platforms(self):
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

    def _make_event_3_platforms(self):
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

    @patch.object(Sat2SatMUFinder, "run_scrappi")
    def test_two_platforms_overlap_and_non_overlap(self, mock_run_scrappi):
        """
        2 platforms, 6 products total:
        - 4 overlapping (2x2)
        - 2 non-overlapping
        Expected: 4 Matchups
        """
        all_products = scrappi.product.open_product_item_set(self.fixture_overlap_2_platforms)
        mock_run_scrappi.side_effect = self._platform_side_effect(all_products)

        finder = self._make_finder()
        event = self._make_event_2_platforms()

        results = finder.to_matchup_set([event])

        self.assertEqual(len(results), 1)
        mu_event = results[0]

        self.assertIsNotNone(mu_event.matchup_set)
        self.assertIsInstance(mu_event.matchup_set, MatchupSet)

        # 2 S2A products x 2 Landsat products = 4
        self.assertEqual(len(mu_event.matchup_set), 4)

        for mu in mu_event.matchup_set:
            self.assertIsInstance(mu, Matchup)
            self.assertEqual(len(mu.products), 2)

    @patch.object(Sat2SatMUFinder, "run_scrappi")
    def test_three_platforms_overlap(self, mock_run_scrappi):
        """
        3 platforms, all overlapping
        Expected: 2 Matchups (S1=1, S2=2, L8=1 → 1×2×1 = 2 combos)
        """
        all_products = scrappi.product.open_product_item_set(self.fixture_overlap_3_platforms)
        mock_run_scrappi.side_effect = self._platform_side_effect(all_products)

        finder = self._make_finder()
        event = self._make_event_3_platforms()

        results = finder.to_matchup_set([event])

        self.assertEqual(len(results), 1)
        mu_event = results[0]

        self.assertIsNotNone(mu_event.matchup_set)

        # S1=1, S2=2, L8=1 → 2 combos
        self.assertEqual(len(mu_event.matchup_set), 2)

        for mu in mu_event.matchup_set:
            self.assertEqual(len(mu.products), 3)

    @patch.object(Sat2SatMUFinder, "run_scrappi")
    def test_no_products_returns_empty(self, mock_run_scrappi):
        mock_run_scrappi.return_value = scrappi.ProductItemSet()

        finder = self._make_finder()
        event = self._make_event_2_platforms()

        results = finder.to_matchup_set([event])

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
if __name__ == "__main__":
    unittest.main()
