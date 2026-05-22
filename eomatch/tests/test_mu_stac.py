"""eomatch.tests.test_mu_stac - tests for STAC serialisation on Matchup and MatchupEvent"""

import datetime as dt
import tempfile
import os
import unittest
from unittest.mock import MagicMock
from shapely.geometry import Polygon, mapping, shape

import pystac

from eomatch.domain import (
    Matchup,
    MatchupEvent,
    MatchupEventSet,
    MatchupSet,
    MATCHUP_EVENTS_COLLECTION_PREFIX,
)
from eomatch.mu_stac import MatchupCatalogue

MATCHUP_COLLECTION_ID = "LANDSAT_C2L1-Landsat-vs-S3_EFR-Sentinel-3"
EVENTS_COLLECTION_ID = "matchup-events-LANDSAT_C2L1-Landsat8-vs-S3_EFR-Sentinel3A"


class _FakeProductItemSet:
    """Minimal ProductItemSet stub — only the interface Matchup needs."""

    def __init__(self, products):
        self._items = products

    def sort(self, sort_by=None):
        pass

    def __getitem__(self, idx):
        return self._items[idx]

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    @property
    def collections(self):
        return [p.collection for p in self._items]


__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = []

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

L8_GEOMETRY = Polygon(
    [
        [-39.54938, 148.72847],
        [-39.96319, 150.9269],
        [-38.24987, 151.42844],
        [-37.84424, 149.28131],
        [-39.54938, 148.72847],
    ]
)

S3_GEOMETRY = Polygon(
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
)

L8_START = dt.datetime(2022, 6, 7, 23, 45, 8, 609447)
L8_STOP = dt.datetime(2022, 6, 7, 23, 45, 40, 379447)
S3_START = dt.datetime(2022, 6, 7, 23, 38, 57, 833000)
S3_STOP = dt.datetime(2022, 6, 7, 23, 41, 57, 833000)

L8_STAC_ID = "LC08_L1GT_089087_20220607_20220616_02_T2"
S3_STAC_ID = "S3A_OL_1_EFR____20220607T233858_20220607T234158_20220608T234813_0180_086_144_3600_PS1_O_NT_002"


def _make_stac_item(id_, collection, platform, geometry, start, stop):
    return pystac.Item(
        id=id_,
        geometry=mapping(geometry),
        bbox=list(geometry.bounds),
        datetime=start,
        properties={
            "platform": platform,
            "end_datetime": stop.isoformat(),
        },
        collection=collection,
    )


def _make_mock_product(platform, collection, id_, geometry, start, stop):
    mock = MagicMock()
    mock.platform = platform
    mock.collection = collection
    mock.id = id_
    mock.geometry = geometry
    mock.start_time = start
    mock.stop_time = stop
    mock.to_stac_item.side_effect = lambda *a, **kw: _make_stac_item(id_, collection, platform, geometry, start, stop)
    return mock


L8_PRODUCT = _make_mock_product("Landsat", "LANDSAT_C2L1", L8_STAC_ID, L8_GEOMETRY, L8_START, L8_STOP)
S3_PRODUCT = _make_mock_product("Sentinel-3", "S3_EFR", S3_STAC_ID, S3_GEOMETRY, S3_START, S3_STOP)


def _make_matchup():
    return Matchup(_FakeProductItemSet([L8_PRODUCT, S3_PRODUCT]))


EVENT = MatchupEvent(
    platforms=["Landsat8", "Sentinel3A"],
    collections=["LANDSAT_C2L1", "S3_EFR"],
    start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
    stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
    latitude_minimum=-46.0,
    longitude_minimum=136.0,
    latitude_maximum=-31.0,
    longitude_maximum=153.0,
)


# ---------------------------------------------------------------------------
# MatchupEvent.to_stac_item / from_stac_item
# ---------------------------------------------------------------------------


class TestMatchupEventToStacItem(unittest.TestCase):
    def setUp(self):
        self.item = EVENT.to_stac_item()

    def test_collection(self):
        self.assertEqual(self.item.collection_id, EVENTS_COLLECTION_ID)

    def test_collection_id_contains_prefix(self):
        self.assertTrue(self.item.collection_id.startswith(MATCHUP_EVENTS_COLLECTION_PREFIX))

    def test_datetime(self):
        self.assertEqual(self.item.datetime, EVENT.start_time)

    def test_end_datetime_in_properties(self):
        self.assertEqual(self.item.properties["end_datetime"], EVENT.stop_time.isoformat())

    def test_platforms_in_properties(self):
        self.assertEqual(self.item.properties["matchup:platforms"], EVENT.platforms)

    def test_collections_in_properties(self):
        self.assertEqual(self.item.properties["matchup:collections"], EVENT.collections)

    def test_bbox(self):
        self.assertEqual(
            self.item.bbox,
            [
                EVENT.geometry["longitude_minimum"],
                EVENT.geometry["latitude_minimum"],
                EVENT.geometry["longitude_maximum"],
                EVENT.geometry["latitude_maximum"],
            ],
        )

    def test_geometry_is_polygon(self):
        self.assertEqual(self.item.geometry["type"], "Polygon")

    def test_id_contains_platforms_and_start_time(self):
        self.assertIn("Landsat8", self.item.id)
        self.assertIn("Sentinel3A", self.item.id)
        self.assertIn(EVENT.start_time.strftime("%Y%m%dT%H%M%S"), self.item.id)


class TestMatchupEventMatchupSet(unittest.TestCase):
    def test_matchup_set_initially_none(self):
        self.assertIsNone(EVENT.matchup_set)

    def test_register_matchup_set(self):
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        mu_set = MatchupSet([_make_matchup()])
        event.matchup_set = mu_set
        self.assertIs(event.matchup_set, mu_set)

    def test_register_wrong_type_raises(self):
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        with self.assertRaises(TypeError):
            event.matchup_set = [_make_matchup()]

    def test_register_mismatched_collections_raises(self):
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        wrong_product = _make_mock_product("Sentinel-2", "S2_MSI", "S2A_tile", L8_GEOMETRY, L8_START, L8_STOP)
        wrong_mu = Matchup(_FakeProductItemSet([wrong_product, S3_PRODUCT]))
        with self.assertRaises(ValueError):
            event.matchup_set = MatchupSet([wrong_mu])


class TestMatchupEventFromStacItem(unittest.TestCase):
    def test_roundtrip(self):
        item = EVENT.to_stac_item()
        event2 = MatchupEvent.from_stac_item(item)

        self.assertEqual(event2.platforms, EVENT.platforms)
        self.assertEqual(event2.collections, EVENT.collections)
        self.assertEqual(event2.start_time, EVENT.start_time)
        self.assertEqual(event2.stop_time, EVENT.stop_time)
        self.assertAlmostEqual(event2.geometry["latitude_minimum"], EVENT.geometry["latitude_minimum"])
        self.assertAlmostEqual(event2.geometry["longitude_minimum"], EVENT.geometry["longitude_minimum"])
        self.assertAlmostEqual(event2.geometry["latitude_maximum"], EVENT.geometry["latitude_maximum"])
        self.assertAlmostEqual(event2.geometry["longitude_maximum"], EVENT.geometry["longitude_maximum"])


# ---------------------------------------------------------------------------
# Matchup.to_stac_item / from_stac_item
# ---------------------------------------------------------------------------


class TestMatchupToStacItem(unittest.TestCase):
    def setUp(self):
        self.mu = _make_matchup()
        self.item = self.mu.to_stac_item()

    def test_datetime(self):
        self.assertEqual(self.item.datetime, S3_START)

    def test_end_datetime_in_properties(self):
        self.assertEqual(self.item.properties["end_datetime"], L8_STOP.isoformat())

    def test_collections_in_properties(self):
        self.assertCountEqual(
            self.item.properties["matchup:collections"],
            ["LANDSAT_C2L1", "S3_EFR"],
        )

    def test_time_diff_abs_in_properties(self):
        self.assertAlmostEqual(
            self.item.properties["matchup:time_diff_abs"],
            self.mu.time_diff_abs,
        )

    def test_collection_id_is_sorted_vs_string(self):
        self.assertEqual(self.item.collection_id, MATCHUP_COLLECTION_ID)

    def test_no_event_id_when_not_provided(self):
        self.assertNotIn("matchup:event_id", self.item.properties)

    def test_event_id_in_properties_when_provided(self):
        event_item = EVENT.to_stac_item()
        item = self.mu.to_stac_item(event_id=event_item.id)
        self.assertEqual(item.properties["matchup:event_id"], event_item.id)

    def test_two_derived_from_links(self):
        derived = [lnk for lnk in self.item.links if lnk.rel == "derived_from"]
        self.assertEqual(len(derived), 2)

    def test_derived_from_targets_are_stac_items(self):
        derived = [lnk for lnk in self.item.links if lnk.rel == "derived_from"]
        for link in derived:
            self.assertIsInstance(link.target, pystac.Item)

    def test_no_event_link_from_to_stac_item(self):
        # Links to the parent event are added by MatchupCatalogue.add_event (which
        # has the resolved pystac.Item as a target).  to_stac_item only records the
        # event ID in properties; it does not create a link.
        event_item = EVENT.to_stac_item()
        item = self.mu.to_stac_item(event_id=event_item.id)
        related = [
            lnk for lnk in item.links if lnk.rel == "related" and lnk.extra_fields.get("matchup:role") == "event"
        ]
        self.assertEqual(len(related), 0)

    def test_no_event_link_without_event_id(self):
        related = [lnk for lnk in self.item.links if lnk.rel == "related"]
        self.assertEqual(len(related), 0)

    def test_geometry_matches_collocation_region(self):
        item_geom = shape(self.item.geometry)
        self.assertTrue(item_geom.equals(self.mu.collocation_region))


# ---------------------------------------------------------------------------
# MatchupCatalogue
# ---------------------------------------------------------------------------


class TestMatchupCatalogue(unittest.TestCase):
    def setUp(self):
        self.catalogue = MatchupCatalogue()
        self.mu = _make_matchup()

    def test_add_event_returns_stac_item(self):
        item = self.catalogue.add_event(EVENT)
        self.assertIsInstance(item, pystac.Item)

    def test_add_event_appears_in_collection(self):
        item = self.catalogue.add_event(EVENT)
        events_col = self.catalogue.catalog.get_child(EVENTS_COLLECTION_ID)
        item_ids = [i.id for i in events_col.get_items()]
        self.assertIn(item.id, item_ids)

    def test_add_matchup_returns_stac_item(self):
        item = self.catalogue.add_matchup(self.mu)
        self.assertIsInstance(item, pystac.Item)

    def test_add_matchup_creates_typed_collection(self):
        self.catalogue.add_matchup(self.mu)
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        self.assertIsNotNone(col)

    def test_add_matchup_with_event_id(self):
        event_item = self.catalogue.add_event(EVENT)
        mu_item = self.catalogue.add_matchup(self.mu, event_id=event_item.id)
        self.assertEqual(mu_item.properties["matchup:event_id"], event_item.id)

    def test_add_matchup_creates_product_collections(self):
        self.catalogue.add_matchup(self.mu)
        self.assertIsNotNone(self.catalogue.catalog.get_child("LANDSAT_C2L1"))
        self.assertIsNotNone(self.catalogue.catalog.get_child("S3_EFR"))

    def test_add_matchup_populates_product_collections(self):
        self.catalogue.add_matchup(self.mu)
        l8_col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        s3_col = self.catalogue.catalog.get_child("S3_EFR")
        self.assertEqual(len(list(l8_col.get_items())), 1)
        self.assertEqual(len(list(s3_col.get_items())), 1)

    def test_add_matchup_derived_from_targets_are_catalogue_items(self):
        self.catalogue.add_matchup(self.mu)
        mu_col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        mu_item = next(mu_col.get_items())
        derived = [lnk for lnk in mu_item.links if lnk.rel == "derived_from"]
        for link in derived:
            self.assertIsInstance(link.target, pystac.Item)

    def test_duplicate_product_not_added_twice(self):
        self.catalogue.add_matchup(self.mu)
        self.catalogue.add_matchup(self.mu)
        l8_col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        self.assertEqual(len(list(l8_col.get_items())), 1)

    def test_second_matchup_reuses_collection(self):
        offset = dt.timedelta(days=1)
        l8_p2 = _make_mock_product(
            "Landsat",
            "LANDSAT_C2L1",
            "L8_ID_2",
            L8_GEOMETRY,
            L8_START + offset,
            L8_STOP + offset,
        )
        s3_p2 = _make_mock_product(
            "Sentinel-3",
            "S3_EFR",
            "S3_ID_2",
            S3_GEOMETRY,
            S3_START + offset,
            S3_STOP + offset,
        )
        mu2 = Matchup(_FakeProductItemSet([l8_p2, s3_p2]))
        self.catalogue.add_matchup(self.mu)
        self.catalogue.add_matchup(mu2)
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        self.assertEqual(len(list(col.get_items())), 2)

    def test_add_event_with_matchup_set_also_adds_matchups(self):
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        event.matchup_set = MatchupSet([self.mu])
        self.catalogue.add_event(event)
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        self.assertIsNotNone(col)
        self.assertEqual(len(list(col.get_items())), 1)

    def test_add_event_with_matchup_set_links_event_id(self):
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        event.matchup_set = MatchupSet([self.mu])
        event_item = self.catalogue.add_event(event)
        mu_item = next(self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID).get_items())
        self.assertEqual(mu_item.properties["matchup:event_id"], event_item.id)

    def test_add_event_adds_related_links_to_matchup_items(self):
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        event.matchup_set = MatchupSet([self.mu])
        event_item = self.catalogue.add_event(event)
        mu_links = [
            lnk
            for lnk in event_item.links
            if lnk.rel == "related" and lnk.extra_fields.get("matchup:role") == "matchup"
        ]
        self.assertEqual(len(mu_links), 1)
        self.assertIsInstance(mu_links[0].target, pystac.Item)

    def test_add_event_without_matchup_set_has_no_matchup_links(self):
        event_item = self.catalogue.add_event(EVENT)
        mu_links = [
            lnk
            for lnk in event_item.links
            if lnk.rel == "related" and lnk.extra_fields.get("matchup:role") == "matchup"
        ]
        self.assertEqual(len(mu_links), 0)

    def test_add_event_without_matchup_set_adds_no_matchups(self):
        self.catalogue.add_event(EVENT)
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        self.assertIsNone(col)

    def test_save_and_open_roundtrip(self):
        self.catalogue.add_event(EVENT)
        self.catalogue.add_matchup(self.mu)

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = os.path.join(tmpdir, "catalog.json")
            self.catalogue.save(tmpdir)

            reopened = MatchupCatalogue.open(root_path)
            event_ids = [i.id for i in reopened.catalog.get_child(EVENTS_COLLECTION_ID).get_items()]
            self.assertEqual(len(event_ids), 1)

            mu_col = reopened.catalog.get_child(MATCHUP_COLLECTION_ID)
            self.assertIsNotNone(mu_col)
            self.assertEqual(len(list(mu_col.get_items())), 1)


class TestMatchupCatalogueAddAsset(unittest.TestCase):
    def setUp(self):
        self.catalogue = MatchupCatalogue()
        self.mu = _make_matchup()
        self.event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        self.event.matchup_set = MatchupSet([self.mu])
        self.catalogue.add_event(self.event)
        self.asset = pystac.Asset(href="/tmp/file.nc", media_type="application/x-netcdf", title="test")

    def test_add_product_asset_returns_true(self):
        self.assertTrue(self.catalogue.add_product_asset(L8_PRODUCT, "data", self.asset))

    def test_add_product_asset_asset_present(self):
        self.catalogue.add_product_asset(L8_PRODUCT, "data", self.asset)
        col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        item = next(col.get_items(L8_STAC_ID))
        self.assertIn("data", item.assets)
        self.assertEqual(item.assets["data"].href, self.asset.href)

    def test_add_product_asset_unknown_product_returns_false(self):
        unknown = _make_mock_product("X", "UNKNOWN_COL", "unknown-id", L8_GEOMETRY, L8_START, L8_STOP)
        self.assertFalse(self.catalogue.add_product_asset(unknown, "data", self.asset))

    def test_add_event_asset_returns_true(self):
        self.assertTrue(self.catalogue.add_event_asset(self.event, "thumbnail", self.asset))

    def test_add_event_asset_asset_present(self):
        self.catalogue.add_event_asset(self.event, "thumbnail", self.asset)
        col = self.catalogue.catalog.get_child(EVENTS_COLLECTION_ID)
        event_item = next(col.get_items())
        self.assertIn("thumbnail", event_item.assets)
        self.assertEqual(event_item.assets["thumbnail"].href, self.asset.href)

    def test_add_event_asset_unknown_event_returns_false(self):
        ghost = MatchupEvent(
            platforms=["PlatformX", "PlatformY"],
            collections=["COL_A", "COL_B"],
            start_time=dt.datetime(2020, 1, 1),
            stop_time=dt.datetime(2020, 1, 2),
            latitude_minimum=0.0,
            longitude_minimum=0.0,
            latitude_maximum=1.0,
            longitude_maximum=1.0,
        )
        self.assertFalse(self.catalogue.add_event_asset(ghost, "thumbnail", self.asset))

    def test_add_matchup_asset_returns_true(self):
        self.assertTrue(self.catalogue.add_matchup_asset(self.mu, "dataset", self.asset))

    def test_add_matchup_asset_asset_present(self):
        self.catalogue.add_matchup_asset(self.mu, "dataset", self.asset)
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        mu_item = next(col.get_items())
        self.assertIn("dataset", mu_item.assets)
        self.assertEqual(mu_item.assets["dataset"].href, self.asset.href)

    def test_add_matchup_asset_unknown_matchup_returns_false(self):
        ghost_mu = Matchup(
            _FakeProductItemSet(
                [
                    _make_mock_product("X", "COL_X", "ghost-1", L8_GEOMETRY, L8_START, L8_STOP),
                    _make_mock_product("Y", "COL_Y", "ghost-2", L8_GEOMETRY, S3_START, S3_STOP),
                ]
            )
        )
        self.assertFalse(self.catalogue.add_matchup_asset(ghost_mu, "dataset", self.asset))

    # --- in-memory sync ---

    def test_add_event_asset_updates_event_assets(self):
        self.catalogue.add_event_asset(self.event, "thumbnail", self.asset)
        self.assertIn("thumbnail", self.event.assets)
        self.assertIs(self.event.assets["thumbnail"], self.asset)

    def test_add_matchup_asset_updates_matchup_assets(self):
        self.catalogue.add_matchup_asset(self.mu, "dataset", self.asset)
        self.assertIn("dataset", self.mu.assets)
        self.assertIs(self.mu.assets["dataset"], self.asset)

    def test_add_event_asset_unknown_does_not_update_event_assets(self):
        ghost = MatchupEvent(
            platforms=["PlatformX", "PlatformY"],
            collections=["COL_A", "COL_B"],
            start_time=dt.datetime(2020, 1, 1),
            stop_time=dt.datetime(2020, 1, 2),
            latitude_minimum=0.0,
            longitude_minimum=0.0,
            latitude_maximum=1.0,
            longitude_maximum=1.0,
        )
        self.catalogue.add_event_asset(ghost, "thumbnail", self.asset)
        self.assertNotIn("thumbnail", ghost.assets)

    def test_add_matchup_asset_unknown_does_not_update_matchup_assets(self):
        ghost_mu = Matchup(
            _FakeProductItemSet(
                [
                    _make_mock_product("X", "COL_X", "ghost-1", L8_GEOMETRY, L8_START, L8_STOP),
                    _make_mock_product("Y", "COL_Y", "ghost-2", L8_GEOMETRY, S3_START, S3_STOP),
                ]
            )
        )
        self.catalogue.add_matchup_asset(ghost_mu, "dataset", self.asset)
        self.assertNotIn("dataset", ghost_mu.assets)


class TestMatchupCatalogueRemoveAsset(unittest.TestCase):
    def setUp(self):
        self.catalogue = MatchupCatalogue()
        self.mu = _make_matchup()
        self.event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        self.event.matchup_set = MatchupSet([self.mu])
        self.catalogue.add_event(self.event)

    def _add_temp_file_asset(self, item, asset_key="data"):
        """Write a temporary file, register it as an asset, return the path."""
        import tempfile

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".nc")
        tmp.close()
        item.assets[asset_key] = pystac.Asset(
            href=tmp.name,
            media_type="application/x-netcdf",
            extra_fields={"scrappi:asset_state": "downloaded"},
        )
        return tmp.name

    # --- remove_product_asset ---

    def test_remove_product_asset_returns_true(self):
        col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        item = next(col.get_items(L8_STAC_ID))
        self._add_temp_file_asset(item)
        self.assertTrue(self.catalogue.remove_product_asset(L8_PRODUCT, "data"))

    def test_remove_product_asset_removes_reference(self):
        col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        item = next(col.get_items(L8_STAC_ID))
        self._add_temp_file_asset(item)
        self.catalogue.remove_product_asset(L8_PRODUCT, "data")
        self.assertNotIn("data", item.assets)

    def test_remove_product_asset_deletes_file(self):
        col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        item = next(col.get_items(L8_STAC_ID))
        path = self._add_temp_file_asset(item)
        self.catalogue.remove_product_asset(L8_PRODUCT, "data", delete_file=True)
        self.assertFalse(os.path.exists(path))

    def test_remove_product_asset_keeps_file_when_delete_false(self):
        col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        item = next(col.get_items(L8_STAC_ID))
        path = self._add_temp_file_asset(item)
        try:
            self.catalogue.remove_product_asset(L8_PRODUCT, "data", delete_file=False)
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_remove_product_asset_url_href_not_deleted(self):
        col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        item = next(col.get_items(L8_STAC_ID))
        item.assets["thumbnail"] = pystac.Asset(href="https://example.com/thumb.jpg")
        # should not raise even though the href is a URL
        result = self.catalogue.remove_product_asset(L8_PRODUCT, "thumbnail")
        self.assertTrue(result)
        self.assertNotIn("thumbnail", item.assets)

    def test_remove_product_asset_missing_asset_returns_false(self):
        self.assertFalse(self.catalogue.remove_product_asset(L8_PRODUCT, "nonexistent"))

    def test_remove_product_asset_unknown_product_returns_false(self):
        unknown = _make_mock_product("X", "UNKNOWN_COL", "unknown-id", L8_GEOMETRY, L8_START, L8_STOP)
        self.assertFalse(self.catalogue.remove_product_asset(unknown, "data"))

    # --- remove_event_asset ---

    def test_remove_event_asset_removes_reference(self):
        col = self.catalogue.catalog.get_child(EVENTS_COLLECTION_ID)
        item = next(col.get_items())
        path = self._add_temp_file_asset(item, "report")
        self.catalogue.remove_event_asset(self.event, "report")
        self.assertNotIn("report", item.assets)
        if os.path.exists(path):
            os.remove(path)

    def test_remove_event_asset_unknown_event_returns_false(self):
        ghost = MatchupEvent(
            platforms=["PlatformX", "PlatformY"],
            collections=["COL_A", "COL_B"],
            start_time=dt.datetime(2020, 1, 1),
            stop_time=dt.datetime(2020, 1, 2),
            latitude_minimum=0.0,
            longitude_minimum=0.0,
            latitude_maximum=1.0,
            longitude_maximum=1.0,
        )
        self.assertFalse(self.catalogue.remove_event_asset(ghost, "report"))

    # --- remove_matchup_asset ---

    def test_remove_matchup_asset_removes_reference(self):
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        item = next(col.get_items())
        path = self._add_temp_file_asset(item, "dataset")
        self.catalogue.remove_matchup_asset(self.mu, "dataset")
        self.assertNotIn("dataset", item.assets)
        if os.path.exists(path):
            os.remove(path)

    def test_remove_matchup_asset_unknown_matchup_returns_false(self):
        ghost_mu = Matchup(
            _FakeProductItemSet(
                [
                    _make_mock_product("X", "COL_X", "ghost-1", L8_GEOMETRY, L8_START, L8_STOP),
                    _make_mock_product("Y", "COL_Y", "ghost-2", L8_GEOMETRY, S3_START, S3_STOP),
                ]
            )
        )
        self.assertFalse(self.catalogue.remove_matchup_asset(ghost_mu, "dataset"))

    # --- in-memory sync ---

    def test_remove_event_asset_updates_event_assets(self):
        self.catalogue.add_event_asset(self.event, "thumbnail", pystac.Asset(href="/tmp/thumb.jpg"))
        self.catalogue.remove_event_asset(self.event, "thumbnail", delete_file=False)
        self.assertNotIn("thumbnail", self.event.assets)

    def test_remove_matchup_asset_updates_matchup_assets(self):
        self.catalogue.add_matchup_asset(self.mu, "dataset", pystac.Asset(href="/tmp/ds.nc"))
        self.catalogue.remove_matchup_asset(self.mu, "dataset", delete_file=False)
        self.assertNotIn("dataset", self.mu.assets)


class TestMatchupCatalogueCollectionAssets(unittest.TestCase):
    def setUp(self):
        self.catalogue = MatchupCatalogue()
        self.mu = _make_matchup()
        self.event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        self.event.matchup_set = MatchupSet([self.mu])
        self.catalogue.add_event(self.event)
        self.asset = pystac.Asset(href="/tmp/report.pdf", media_type="application/pdf", title="report")

    # --- add_matchup_collection_asset ---

    def test_add_matchup_collection_asset_returns_true(self):
        self.assertTrue(self.catalogue.add_matchup_collection_asset(self.mu, "report", self.asset))

    def test_add_matchup_collection_asset_asset_present(self):
        self.catalogue.add_matchup_collection_asset(self.mu, "report", self.asset)
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        self.assertIn("report", col.assets)
        self.assertEqual(col.assets["report"].href, self.asset.href)

    def test_add_matchup_collection_asset_unknown_returns_false(self):
        ghost_mu = Matchup(
            _FakeProductItemSet(
                [
                    _make_mock_product("X", "COL_X", "ghost-1", L8_GEOMETRY, L8_START, L8_STOP),
                    _make_mock_product("Y", "COL_Y", "ghost-2", L8_GEOMETRY, S3_START, S3_STOP),
                ]
            )
        )
        self.assertFalse(self.catalogue.add_matchup_collection_asset(ghost_mu, "report", self.asset))

    # --- add_event_collection_asset ---

    def test_add_event_collection_asset_returns_true(self):
        self.assertTrue(self.catalogue.add_event_collection_asset(self.event, "summary", self.asset))

    def test_add_event_collection_asset_asset_present(self):
        self.catalogue.add_event_collection_asset(self.event, "summary", self.asset)
        col = self.catalogue.catalog.get_child(EVENTS_COLLECTION_ID)
        self.assertIn("summary", col.assets)
        self.assertEqual(col.assets["summary"].href, self.asset.href)

    def test_add_event_collection_asset_unknown_returns_false(self):
        ghost = MatchupEvent(
            platforms=["PlatformX", "PlatformY"],
            collections=["COL_A", "COL_B"],
            start_time=dt.datetime(2020, 1, 1),
            stop_time=dt.datetime(2020, 1, 2),
            latitude_minimum=0.0,
            longitude_minimum=0.0,
            latitude_maximum=1.0,
            longitude_maximum=1.0,
        )
        self.assertFalse(self.catalogue.add_event_collection_asset(ghost, "summary", self.asset))

    # --- remove_matchup_collection_asset ---

    def test_remove_matchup_collection_asset_returns_true(self):
        self.catalogue.add_matchup_collection_asset(self.mu, "report", self.asset)
        self.assertTrue(self.catalogue.remove_matchup_collection_asset(self.mu, "report", delete_file=False))

    def test_remove_matchup_collection_asset_removes_reference(self):
        self.catalogue.add_matchup_collection_asset(self.mu, "report", self.asset)
        self.catalogue.remove_matchup_collection_asset(self.mu, "report", delete_file=False)
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        self.assertNotIn("report", col.assets)

    def test_remove_matchup_collection_asset_missing_returns_false(self):
        self.assertFalse(self.catalogue.remove_matchup_collection_asset(self.mu, "nonexistent"))

    def test_remove_matchup_collection_asset_unknown_collection_returns_false(self):
        ghost_mu = Matchup(
            _FakeProductItemSet(
                [
                    _make_mock_product("X", "COL_X", "ghost-1", L8_GEOMETRY, L8_START, L8_STOP),
                    _make_mock_product("Y", "COL_Y", "ghost-2", L8_GEOMETRY, S3_START, S3_STOP),
                ]
            )
        )
        self.assertFalse(self.catalogue.remove_matchup_collection_asset(ghost_mu, "report"))

    # --- remove_event_collection_asset ---

    def test_remove_event_collection_asset_removes_reference(self):
        self.catalogue.add_event_collection_asset(self.event, "summary", self.asset)
        self.catalogue.remove_event_collection_asset(self.event, "summary", delete_file=False)
        col = self.catalogue.catalog.get_child(EVENTS_COLLECTION_ID)
        self.assertNotIn("summary", col.assets)

    def test_remove_event_collection_asset_missing_returns_false(self):
        self.assertFalse(self.catalogue.remove_event_collection_asset(self.event, "nonexistent"))

    def test_remove_event_collection_asset_deletes_file(self):
        import tempfile

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.close()
        try:
            self.catalogue.add_event_collection_asset(self.event, "summary", pystac.Asset(href=tmp.name))
            self.catalogue.remove_event_collection_asset(self.event, "summary", delete_file=True)
            self.assertFalse(os.path.exists(tmp.name))
        finally:
            if os.path.exists(tmp.name):
                os.remove(tmp.name)


class TestMatchupCatalogueGetEvents(unittest.TestCase):
    def _make_event_with_matchup_set(self):
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        event.matchup_set = MatchupSet([_make_matchup()])
        return event

    def setUp(self):
        self.catalogue = MatchupCatalogue()
        self.event = self._make_event_with_matchup_set()
        self.catalogue.add_event(self.event)

    def test_get_events_returns_matchup_event_set(self):
        self.assertIsInstance(self.catalogue.get_events(), MatchupEventSet)

    def test_get_events_count(self):
        self.assertEqual(len(self.catalogue.get_events()), 1)

    def test_get_events_returns_matchup_event_objects(self):
        events = self.catalogue.get_events()
        self.assertIsInstance(events[0], MatchupEvent)

    def test_get_events_event_platforms(self):
        events = self.catalogue.get_events()
        self.assertEqual(events[0].platforms, self.event.platforms)

    def test_get_events_event_collections(self):
        events = self.catalogue.get_events()
        self.assertEqual(sorted(events[0].collections), sorted(self.event.collections))

    def test_get_events_event_times(self):
        events = self.catalogue.get_events()
        self.assertEqual(events[0].start_time, self.event.start_time)
        self.assertEqual(events[0].stop_time, self.event.stop_time)

    def test_get_events_matchup_set_populated(self):
        events = self.catalogue.get_events()
        self.assertIsNotNone(events[0].matchup_set)

    def test_get_events_matchup_set_count(self):
        events = self.catalogue.get_events()
        self.assertEqual(len(events[0].matchup_set), 1)

    def test_get_events_matchup_product_count(self):
        events = self.catalogue.get_events()
        matchup = events[0].matchup_set[0]
        self.assertEqual(len(matchup.products), 2)

    def test_get_events_matchup_product_collections(self):
        events = self.catalogue.get_events()
        matchup = events[0].matchup_set[0]
        self.assertCountEqual(
            [p.collection for p in matchup.products],
            ["LANDSAT_C2L1", "S3_EFR"],
        )

    def test_get_events_filter_matching_collections(self):
        events = self.catalogue.get_events(collections=["LANDSAT_C2L1", "S3_EFR"])
        self.assertEqual(len(events), 1)

    def test_get_events_filter_no_match(self):
        events = self.catalogue.get_events(collections=["S2_MSI", "S3_EFR"])
        self.assertEqual(len(events), 0)

    def test_get_events_empty_catalogue(self):
        cat = MatchupCatalogue()
        self.assertEqual(len(cat.get_events()), 0)

    def test_get_events_event_without_matchups_has_no_matchup_set(self):
        cat = MatchupCatalogue()
        cat.add_event(EVENT)  # EVENT has no matchup_set
        events = cat.get_events()
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].matchup_set)

    def test_get_events_multiple_events(self):
        event2 = self._make_event_with_matchup_set()
        # give it a distinct start time so it gets a different item ID
        event2.start_time = dt.datetime(2022, 6, 8, 10, 0, 0, tzinfo=dt.timezone.utc)
        self.catalogue.add_event(event2)
        events = self.catalogue.get_events()
        self.assertEqual(len(events), 2)

    # --- platforms filter ---

    def test_get_events_filter_platform_match(self):
        events = self.catalogue.get_events(platforms=["Landsat8"])
        self.assertEqual(len(events), 1)

    def test_get_events_filter_platform_no_match(self):
        events = self.catalogue.get_events(platforms=["Sentinel2A"])
        self.assertEqual(len(events), 0)

    def test_get_events_filter_platform_any_match(self):
        events = self.catalogue.get_events(platforms=["Sentinel2A", "Landsat8"])
        self.assertEqual(len(events), 1)

    # --- temporal filter ---

    def test_get_events_filter_start_time_within(self):
        # query window starts before event stops → included
        events = self.catalogue.get_events(start_time=dt.datetime(2022, 6, 7, 23, 30, 0))
        self.assertEqual(len(events), 1)

    def test_get_events_filter_start_time_after_event(self):
        # query window starts after event ends → excluded
        events = self.catalogue.get_events(start_time=dt.datetime(2022, 6, 8, 0, 0, 0))
        self.assertEqual(len(events), 0)

    def test_get_events_filter_stop_time_within(self):
        # query window ends after event starts → included
        events = self.catalogue.get_events(stop_time=dt.datetime(2022, 6, 7, 23, 30, 0))
        self.assertEqual(len(events), 1)

    def test_get_events_filter_stop_time_before_event(self):
        # query window ends before event starts → excluded
        events = self.catalogue.get_events(stop_time=dt.datetime(2022, 6, 7, 22, 0, 0))
        self.assertEqual(len(events), 0)

    def test_get_events_filter_time_window_overlapping(self):
        events = self.catalogue.get_events(
            start_time=dt.datetime(2022, 6, 7, 22, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 30, 0),
        )
        self.assertEqual(len(events), 1)

    # --- bbox filter ---

    def test_get_events_filter_bbox_overlapping(self):
        # bbox inside event extent → included
        events = self.catalogue.get_events(bbox=[140.0, -40.0, 150.0, -35.0])
        self.assertEqual(len(events), 1)

    def test_get_events_filter_bbox_non_overlapping(self):
        # bbox entirely west of event extent → excluded
        events = self.catalogue.get_events(bbox=[0.0, -40.0, 10.0, -35.0])
        self.assertEqual(len(events), 0)

    def test_get_events_after_save_and_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = os.path.join(tmpdir, "catalog.json")
            self.catalogue.save(tmpdir)
            reopened = MatchupCatalogue.open(root_path)
            events = reopened.get_events()
            self.assertEqual(len(events), 1)
            self.assertIsNotNone(events[0].matchup_set)
            self.assertEqual(len(events[0].matchup_set), 1)

    # --- products_downloaded filter ---

    def _mark_products_downloaded(self):
        """Add a downloaded data asset to every product item in the catalogue."""
        downloaded_asset = pystac.Asset(
            href="/tmp/fake.nc",
            media_type="application/x-netcdf",
            extra_fields={"scrappi:asset_state": "downloaded"},
        )
        for col_id in ["LANDSAT_C2L1", "S3_EFR"]:
            col = self.catalogue.catalog.get_child(col_id)
            if col is not None:
                for item in col.get_items():
                    item.assets["data"] = downloaded_asset

    def test_products_downloaded_false_returns_event_regardless(self):
        # default: no filter, event returned even without downloaded assets
        events = self.catalogue.get_events(products_downloaded=False)
        self.assertEqual(len(events), 1)

    def test_products_downloaded_excludes_event_when_no_assets(self):
        # no data assets set → event is dropped
        events = self.catalogue.get_events(products_downloaded=True)
        self.assertEqual(len(events), 0)

    def test_products_downloaded_includes_event_when_all_downloaded(self):
        self._mark_products_downloaded()
        events = self.catalogue.get_events(products_downloaded=True)
        self.assertEqual(len(events), 1)

    def test_products_downloaded_matchup_set_populated(self):
        self._mark_products_downloaded()
        events = self.catalogue.get_events(products_downloaded=True)
        self.assertIsNotNone(events[0].matchup_set)
        self.assertEqual(len(events[0].matchup_set), 1)

    def test_products_downloaded_partial_excludes_undownloaded_matchup(self):
        # mark only L8 downloaded; S3 has no asset → matchup excluded → event dropped
        col = self.catalogue.catalog.get_child("LANDSAT_C2L1")
        for item in col.get_items():
            item.assets["data"] = pystac.Asset(
                href="/tmp/l8.nc",
                extra_fields={"scrappi:asset_state": "downloaded"},
            )
        events = self.catalogue.get_events(products_downloaded=True)
        self.assertEqual(len(events), 0)


class TestMatchupEventAssetsRoundtrip(unittest.TestCase):
    def test_assets_empty_by_default(self):
        event = MatchupEvent.from_stac_item(EVENT.to_stac_item())
        self.assertEqual(event.assets, {})

    def test_assets_preserved_via_from_stac_item(self):
        item = EVENT.to_stac_item()
        test_asset = pystac.Asset(href="/tmp/report.pdf", media_type="application/pdf", title="report")
        item.assets["report"] = test_asset
        event = MatchupEvent.from_stac_item(item)
        self.assertIn("report", event.assets)
        self.assertEqual(event.assets["report"].href, "/tmp/report.pdf")

    def test_multiple_assets_preserved(self):
        item = EVENT.to_stac_item()
        item.assets["a"] = pystac.Asset(href="/tmp/a.nc")
        item.assets["b"] = pystac.Asset(href="/tmp/b.tif")
        event = MatchupEvent.from_stac_item(item)
        self.assertIn("a", event.assets)
        self.assertIn("b", event.assets)

    def test_assets_accessible_after_get_events(self):
        catalogue = MatchupCatalogue()
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        event.matchup_set = MatchupSet([_make_matchup()])
        catalogue.add_event(event)

        col = catalogue.catalog.get_child(EVENTS_COLLECTION_ID)
        item = next(col.get_items())
        item.assets["thumbnail"] = pystac.Asset(href="https://example.com/thumb.jpg")

        events = catalogue.get_events()
        self.assertIn("thumbnail", events[0].assets)
        self.assertEqual(events[0].assets["thumbnail"].href, "https://example.com/thumb.jpg")


class TestMatchupAssetsRoundtrip(unittest.TestCase):
    def test_assets_empty_by_default(self):
        mu = _make_matchup()
        item = mu.to_stac_item()
        mu2 = Matchup.from_stac_item(item)
        self.assertEqual(mu2.assets, {})

    def test_assets_preserved_via_from_stac_item(self):
        mu = _make_matchup()
        item = mu.to_stac_item()
        test_asset = pystac.Asset(href="/tmp/result.nc", media_type="application/x-netcdf", title="result")
        item.assets["dataset"] = test_asset
        mu2 = Matchup.from_stac_item(item)
        self.assertIn("dataset", mu2.assets)
        self.assertEqual(mu2.assets["dataset"].href, "/tmp/result.nc")

    def test_multiple_assets_preserved(self):
        mu = _make_matchup()
        item = mu.to_stac_item()
        item.assets["a"] = pystac.Asset(href="/tmp/a.nc")
        item.assets["b"] = pystac.Asset(href="/tmp/b.nc")
        mu2 = Matchup.from_stac_item(item)
        self.assertIn("a", mu2.assets)
        self.assertIn("b", mu2.assets)

    def test_assets_accessible_after_get_events(self):
        catalogue = MatchupCatalogue()
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        event.matchup_set = MatchupSet([_make_matchup()])
        catalogue.add_event(event)

        mu_col = catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        mu_item = next(mu_col.get_items())
        mu_item.assets["dataset"] = pystac.Asset(href="/tmp/mu_result.nc")

        events = catalogue.get_events()
        matchup = events[0].matchup_set[0]
        self.assertIn("dataset", matchup.assets)
        self.assertEqual(matchup.assets["dataset"].href, "/tmp/mu_result.nc")


# ---------------------------------------------------------------------------
# _properties_match
# ---------------------------------------------------------------------------


class TestPropertiesMatch(unittest.TestCase):
    def _make_item(self, **props):
        item = pystac.Item(
            id="test",
            geometry=None,
            bbox=None,
            datetime=dt.datetime(2022, 1, 1),
            properties=props,
        )
        return item

    def test_equality_match(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(status="ok")
        self.assertTrue(_properties_match(item, {"status": "ok"}))

    def test_equality_no_match(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(status="ok")
        self.assertFalse(_properties_match(item, {"status": "bad"}))

    def test_lt_passes(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=5.0)
        self.assertTrue(_properties_match(item, {"v": {"lt": 10.0}}))

    def test_lt_fails_at_boundary(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=10.0)
        self.assertFalse(_properties_match(item, {"v": {"lt": 10.0}}))

    def test_lte_passes_at_boundary(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=10.0)
        self.assertTrue(_properties_match(item, {"v": {"lte": 10.0}}))

    def test_gt_passes(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=15.0)
        self.assertTrue(_properties_match(item, {"v": {"gt": 10.0}}))

    def test_gt_fails_at_boundary(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=10.0)
        self.assertFalse(_properties_match(item, {"v": {"gt": 10.0}}))

    def test_gte_passes_at_boundary(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=10.0)
        self.assertTrue(_properties_match(item, {"v": {"gte": 10.0}}))

    def test_ne_match(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=5.0)
        self.assertTrue(_properties_match(item, {"v": {"ne": 99.0}}))

    def test_ne_no_match(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=5.0)
        self.assertFalse(_properties_match(item, {"v": {"ne": 5.0}}))

    def test_in_match(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(status="ok")
        self.assertTrue(_properties_match(item, {"status": {"in": ["ok", "warn"]}}))

    def test_in_no_match(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(status="error")
        self.assertFalse(_properties_match(item, {"status": {"in": ["ok", "warn"]}}))

    def test_multiple_operators_all_pass(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=5.0)
        self.assertTrue(_properties_match(item, {"v": {"gte": 0.0, "lt": 10.0}}))

    def test_multiple_operators_one_fails(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=5.0)
        self.assertFalse(_properties_match(item, {"v": {"gte": 0.0, "lt": 3.0}}))

    def test_multiple_keys_all_pass(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(a=1.0, b=2.0)
        self.assertTrue(_properties_match(item, {"a": {"lt": 5.0}, "b": {"gt": 1.0}}))

    def test_multiple_keys_one_fails(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(a=1.0, b=2.0)
        self.assertFalse(_properties_match(item, {"a": {"lt": 5.0}, "b": {"gt": 10.0}}))

    def test_missing_key_returns_false(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(a=1.0)
        self.assertFalse(_properties_match(item, {"missing": {"lt": 5.0}}))

    def test_unknown_operator_raises(self):
        from eomatch.mu_stac import _properties_match

        item = self._make_item(v=1.0)
        with self.assertRaises(ValueError):
            _properties_match(item, {"v": {"contains": 1.0}})


# ---------------------------------------------------------------------------
# get_events(properties=...)
# ---------------------------------------------------------------------------


class TestMatchupCatalogueGetEventsPropertiesFilter(unittest.TestCase):
    def setUp(self):
        self.catalogue = MatchupCatalogue()
        event = MatchupEvent(
            platforms=["Landsat8", "Sentinel3A"],
            collections=["LANDSAT_C2L1", "S3_EFR"],
            start_time=dt.datetime(2022, 6, 7, 23, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 23, 59, 59),
            latitude_minimum=-46.0,
            longitude_minimum=136.0,
            latitude_maximum=-31.0,
            longitude_maximum=153.0,
        )
        event.matchup_set = MatchupSet([_make_matchup()])
        self.catalogue.add_event(event)

        # Inject a synthetic enriched property directly onto the matchup item.
        for col in self.catalogue.catalog.get_children():
            if "-vs-" in col.id and not col.id.startswith(f"{MATCHUP_EVENTS_COLLECTION_PREFIX}-"):
                for item in col.get_items():
                    item.properties["time_diff_s"] = 100.0
                    item.properties["land_fraction"] = 0.05

    def test_matching_filter_returns_event(self):
        events = self.catalogue.get_events(properties={"time_diff_s": {"lt": 200.0}})
        self.assertEqual(len(events), 1)

    def test_non_matching_filter_drops_event(self):
        events = self.catalogue.get_events(properties={"time_diff_s": {"lt": 50.0}})
        self.assertEqual(len(events), 0)

    def test_multiple_conditions_all_pass(self):
        events = self.catalogue.get_events(properties={"time_diff_s": {"lt": 200.0}, "land_fraction": {"lt": 0.1}})
        self.assertEqual(len(events), 1)

    def test_multiple_conditions_one_fails(self):
        events = self.catalogue.get_events(properties={"time_diff_s": {"lt": 200.0}, "land_fraction": {"gt": 0.5}})
        self.assertEqual(len(events), 0)

    def test_missing_property_drops_matchup(self):
        # Filter on a key that was never set — matchup should be excluded.
        events = self.catalogue.get_events(properties={"cloud_cover": {"lt": 0.2}})
        self.assertEqual(len(events), 0)

    def test_properties_none_applies_no_filter(self):
        # Default (no properties filter) returns everything.
        events = self.catalogue.get_events(properties=None)
        self.assertEqual(len(events), 1)

    def test_equality_filter(self):
        events = self.catalogue.get_events(properties={"time_diff_s": 100.0})
        self.assertEqual(len(events), 1)

    def test_equality_filter_no_match(self):
        events = self.catalogue.get_events(properties={"time_diff_s": 999.0})
        self.assertEqual(len(events), 0)


if __name__ == "__main__":
    unittest.main()
