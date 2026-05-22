"""eomatch.tests.test_domain - tests for eomatch.domain"""

import unittest

from eomatch.domain import Matchup, MatchupEvent, MatchupEventSet, MatchupSet
from scrappi import ProductItem, ProductItemSet
from shapely.geometry import Polygon
import shapely
import datetime as dt

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = []


L8_PRODUCT_ITEM = ProductItem(
    constellation="Landsat",
    platform="Landsat",
    collection="LANDSAT_C2L1",
    id="LC08_L1GT_089087_20220607_20220616_02_T2",
    geometry=Polygon(
        [
            [-39.54938, 148.72847],
            [-39.96319, 150.9269],
            [-38.24987, 151.42844],
            [-37.84424, 149.28131],
            [-39.54938, 148.72847],
        ]
    ),
    start_time=dt.datetime(2022, 6, 7, 23, 45, 8, 609447),
    stop_time=dt.datetime(2022, 6, 7, 23, 45, 40, 379447),
)


L8_PRODUCT_ITEM_MOVED = ProductItem(
    constellation="Landsat",
    platform="Landsat",
    collection="LANDSAT_C2L1",
    id="LC08_L1GT_089087_20220607_20220616_02_T2",
    geometry=Polygon(
        [
            [-39.54938, 48.72847],
            [-39.96319, 50.9269],
            [-38.24987, 51.42844],
            [-37.84424, 49.28131],
            [-39.54938, 48.72847],
        ]
    ),
    start_time=dt.datetime(2022, 6, 7, 23, 45, 8, 609447),
    stop_time=dt.datetime(2022, 6, 7, 23, 45, 40, 379447),
)

S3_PRODUCT_ITEM = ProductItem(
    constellation="Sentinel-3",
    platform="Sentinel-3",
    collection="S3_EFR",
    id="S3A_OL_1_EFR____20220607T233858_20220607T234158_20220608T234813_0180_086_144_3600_PS1_O_NT_002",
    geometry=Polygon(
        [
            (-45.0568, 150.247),
            (-42.4358, 151.007),
            (-39.8049, 151.734),
            (-37.17, 152.428),
            (-34.5322, 153.097),
            (-34.4043, 152.361),
            (-34.2719, 151.626),
            (-34.1354, 150.895),
            (-33.9954, 150.165),
            (-33.8478, 149.44),
            (-33.6982, 148.716),
            (-33.5411, 147.994),
            (-33.3857, 147.276),
            (-33.2225, 146.557),
            (-33.061, 145.844),
            (-32.8901, 145.132),
            (-32.7147, 144.421),
            (-32.5368, 143.718),
            (-32.354, 143.014),
            (-32.1686, 142.318),
            (-31.978, 141.619),
            (-31.7844, 140.927),
            (-31.5866, 140.236),
            (-31.383, 139.544),
            (-33.9398, 138.477),
            (-36.4838, 137.334),
            (-39.0131, 136.103),
            (-41.5185, 134.776),
            (-41.7555, 135.541),
            (-41.987, 136.314),
            (-42.2143, 137.095),
            (-42.4347, 137.876),
            (-42.6509, 138.668),
            (-42.8602, 139.46),
            (-43.0644, 140.259),
            (-43.2637, 141.065),
            (-43.458, 141.879),
            (-43.641, 142.697),
            (-43.8228, 143.517),
            (-43.9958, 144.341),
            (-44.1681, 145.17),
            (-44.3318, 146.006),
            (-44.4916, 146.845),
            (-44.6419, 147.692),
            (-44.7865, 148.54),
            (-44.9245, 149.39),
            (-45.0568, 150.247),
        ]
    ),
    start_time=dt.datetime(2022, 6, 7, 23, 38, 57, 833000),
    stop_time=dt.datetime(2022, 6, 7, 23, 41, 57, 833000),
)

MU_PRODUCT_ITEMS = ProductItemSet([L8_PRODUCT_ITEM, S3_PRODUCT_ITEM])
NOT_MU_PRODUCT_ITEMS = ProductItemSet([L8_PRODUCT_ITEM, L8_PRODUCT_ITEM_MOVED])


EVENT_1 = MatchupEvent(
    platforms=["Landsat8", "Sentinel3A"],
    collections=["LANDSAT_C2L1", "S3_EFR"],
    start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
    stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
    latitude_minimum=-46.0,
    longitude_minimum=136.0,
    latitude_maximum=-31.0,
    longitude_maximum=153.0,
)

EVENT_2 = MatchupEvent(
    platforms=["Landsat8", "Sentinel3A"],
    collections=["LANDSAT_C2L1", "S3_EFR"],
    start_time=dt.datetime(2022, 6, 8, 23, 0, 0),
    stop_time=dt.datetime(2022, 6, 8, 23, 59, 59),
    latitude_minimum=-46.0,
    longitude_minimum=136.0,
    latitude_maximum=-31.0,
    longitude_maximum=153.0,
)


class TestMatchupEventSet(unittest.TestCase):
    def setUp(self):
        self.events = [EVENT_1, EVENT_2]

    def test___init__(self):
        mes = MatchupEventSet(self.events)
        self.assertCountEqual(mes._events, self.events)

    def test___init__empty(self):
        mes = MatchupEventSet()
        self.assertEqual(mes._events, [])

    def test___len__(self):
        mes = MatchupEventSet(self.events)
        self.assertEqual(len(mes), 2)

    def test___getitem__(self):
        mes = MatchupEventSet(self.events)
        self.assertIs(mes[0], EVENT_1)
        self.assertIs(mes[1], EVENT_2)

    def test___iter__(self):
        mes = MatchupEventSet(self.events)
        self.assertEqual(list(mes), self.events)

    def test_append(self):
        mes = MatchupEventSet([EVENT_1])
        mes.append(EVENT_2)
        self.assertEqual(len(mes), 2)
        self.assertIs(mes[1], EVENT_2)


class TestMatchupSet(unittest.TestCase):
    def setUp(self) -> None:
        self.matchups = [Matchup(MU_PRODUCT_ITEMS), Matchup(MU_PRODUCT_ITEMS)]

    def test___init__(self):
        mus = MatchupSet(self.matchups)
        self.assertCountEqual(mus._matchups, self.matchups)
        self.assertIsNone(mus._collections)

    def test___len__(self):
        mus = MatchupSet(self.matchups)
        self.assertEqual(len(mus), 2)

    def test___getitem__(self):
        mus = MatchupSet(self.matchups)
        mus[0].products[0].id = L8_PRODUCT_ITEM.id

    def test___iter__(self):
        mus = MatchupSet(self.matchups)
        exp_0_ids = [mu.products[0].id for mu in self.matchups]
        for mu, exp_id in zip(mus, exp_0_ids):
            self.assertEqual(mu.products[0].id, exp_id)

    def test_collections(self):
        mus = MatchupSet(self.matchups)
        self.assertCountEqual(
            mus.collections,
            [(L8_PRODUCT_ITEM.collection, S3_PRODUCT_ITEM.collection)],
        )

    def test_collections_preset(self):
        mus = MatchupSet(self.matchups)
        mus._collections = "test"
        self.assertEqual(mus.collections, "test")

    def test_append(self):
        pass


class TestMatchup(unittest.TestCase):
    def setUp(self) -> None:
        self.mu = Matchup(MU_PRODUCT_ITEMS)

    def test___init___None(self):
        mu = Matchup()
        self.assertIsNone(mu.products)

    def test___init__(self):
        self.assertCountEqual([p.id for p in self.mu.products], [p.id for p in MU_PRODUCT_ITEMS])

    def test_product_time_bounds_None(self):
        self.assertIsNone(Matchup().product_time_bounds)

    def test_product_time_bounds(self):
        exp_min_time = dt.datetime(2022, 6, 7, 23, 38, 57, 833000).strftime("%m/%d/%Y, %H:%M:%S.%f")
        exp_max_time = dt.datetime(2022, 6, 7, 23, 45, 40, 379447).strftime("%m/%d/%Y, %H:%M:%S.%f")
        time_bounds = self.mu.product_time_bounds
        self.assertEqual(time_bounds[0].strftime("%m/%d/%Y, %H:%M:%S.%f"), exp_min_time)
        self.assertEqual(time_bounds[1].strftime("%m/%d/%Y, %H:%M:%S.%f"), exp_max_time)

    def test_collocation_region(self):
        col_reg = self.mu.collocation_region
        self.assertTrue(shapely.equals(col_reg, L8_PRODUCT_ITEM.geometry))

    def test_collocation_region_None(self):
        mu = Matchup()
        self.assertIsNone(mu.collocation_region)

    def test_collocation_region_no_overlap(self):
        mu = Matchup()
        mu._products = NOT_MU_PRODUCT_ITEMS
        col_reg = mu.collocation_region
        self.assertTrue(col_reg.is_empty)

    def test_time_diff_abs(self):
        self.assertEqual(
            self.mu.time_diff_abs,
            dt.timedelta(seconds=370, microseconds=776447).total_seconds(),
        )

    def test_time_diff(self):
        td = self.mu.time_diff("S3_EFR", "LANDSAT_C2L1")
        self.assertEqual(td, dt.timedelta(seconds=370, microseconds=776447).total_seconds())

        td = self.mu.time_diff("LANDSAT_C2L1", "S3_EFR")
        self.assertEqual(td, -dt.timedelta(seconds=370, microseconds=776447).total_seconds())

    def test_time_no_collection(self):
        td = self.mu.time_diff()
        self.assertEqual(td, -dt.timedelta(seconds=370, microseconds=776447).total_seconds())

    def test_time_diff_None(self):
        mu = Matchup()
        self.assertIsNone(mu.time_diff())

    def test_return_matchup_dataset_raises_without_products(self):
        mu = Matchup()
        with self.assertRaises(ValueError):
            mu.return_matchup_dataset()


if __name__ == "__main__":
    unittest.main()
