"""eomatch.tests.test_enrich — tests for eomatch.enrich (enrich function and CLI loader)."""

import datetime as dt
import json
import tempfile
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock
from shapely.geometry import Polygon, mapping

import pystac

from eomatch.domain import (
    Matchup,
    MatchupEvent,
    MatchupSet,
)
from eomatch.enrich import enrich, _load_enricher
from eomatch.mu_stac import MatchupCatalogue

# ---------------------------------------------------------------------------
# Shared fixtures (same pattern as test_mu_stac.py)
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
        (-33.5411, 147.994),
        (-33.061, 145.844),
        (-31.383, 139.544),
        (-33.9398, 138.477),
        (-41.5185, 134.776),
        (-44.9245, 149.39),
        (-45.0568, 150.247),
    ]
)

L8_START = dt.datetime(2022, 6, 7, 23, 45, 8)
L8_STOP = dt.datetime(2022, 6, 7, 23, 45, 40)
S3_START = dt.datetime(2022, 6, 7, 23, 38, 57)
S3_STOP = dt.datetime(2022, 6, 7, 23, 41, 57)

L8_ID = "LC08_L1GT_089087_20220607_20220616_02_T2"
S3_ID = "S3A_OL_1_EFR____20220607T233858_20220607T234158"


class _FakeProductItemSet:
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


def _make_stac_item(id_, collection, platform, geometry, start, stop):
    return pystac.Item(
        id=id_,
        geometry=mapping(geometry),
        bbox=list(geometry.bounds),
        datetime=start,
        properties={"platform": platform, "end_datetime": stop.isoformat()},
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


L8_PRODUCT = _make_mock_product("Landsat", "LANDSAT_C2L1", L8_ID, L8_GEOMETRY, L8_START, L8_STOP)
S3_PRODUCT = _make_mock_product("Sentinel-3", "S3_EFR", S3_ID, S3_GEOMETRY, S3_START, S3_STOP)


def _make_catalogue_with_matchup():
    """Return a MatchupCatalogue containing one event with one matchup."""
    mu = Matchup(_FakeProductItemSet([L8_PRODUCT, S3_PRODUCT]))
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
    event.matchup_set = MatchupSet([mu])
    catalogue = MatchupCatalogue()
    catalogue.add_event(event)
    return catalogue


# ---------------------------------------------------------------------------
# Trivial enrichers used in tests
# ---------------------------------------------------------------------------


def _enricher_constant(matchup) -> Dict[str, Any]:
    """Always returns a fixed property."""
    return {"test_prop": 42}


def _enricher_two_keys(matchup) -> Dict[str, Any]:
    return {"key_a": 1, "key_b": 2}


def _enricher_raises(matchup) -> Dict[str, Any]:
    raise RuntimeError("deliberate failure")


# ---------------------------------------------------------------------------
# Tests for enrich()
# ---------------------------------------------------------------------------


class TestEnrichFunction(unittest.TestCase):
    def setUp(self):
        self.catalogue = _make_catalogue_with_matchup()

    def _get_mu_item(self):
        """Return the single matchup pystac.Item from the catalogue."""
        from eomatch.domain import MATCHUP_EVENTS_COLLECTION_PREFIX

        prefix = f"{MATCHUP_EVENTS_COLLECTION_PREFIX}-"
        for col in self.catalogue.catalog.get_children():
            if col.id.startswith(prefix) or "-vs-" not in col.id:
                continue
            return next(col.get_items())
        raise AssertionError("No matchup item found")

    def test_adds_property_to_matchup_item(self):
        enrich(self.catalogue, enrichers=[_enricher_constant])
        item = self._get_mu_item()
        self.assertIn("test_prop", item.properties)
        self.assertEqual(item.properties["test_prop"], 42)

    def test_adds_multiple_properties(self):
        enrich(self.catalogue, enrichers=[_enricher_two_keys])
        item = self._get_mu_item()
        self.assertIn("key_a", item.properties)
        self.assertIn("key_b", item.properties)

    def test_returns_count_of_enriched_items(self):
        count = enrich(self.catalogue, enrichers=[_enricher_constant])
        self.assertEqual(count, 1)

    def test_returns_zero_when_no_matchup_collections(self):
        empty = MatchupCatalogue()
        count = enrich(empty, enrichers=[_enricher_constant])
        self.assertEqual(count, 0)

    def test_overwrite_false_keeps_existing_property(self):
        item = self._get_mu_item()
        item.properties["test_prop"] = 99
        enrich(self.catalogue, enrichers=[_enricher_constant], overwrite=False)
        self.assertEqual(item.properties["test_prop"], 99)

    def test_overwrite_true_replaces_existing_property(self):
        item = self._get_mu_item()
        item.properties["test_prop"] = 99
        enrich(self.catalogue, enrichers=[_enricher_constant], overwrite=True)
        self.assertEqual(item.properties["test_prop"], 42)

    def test_failing_enricher_does_not_raise(self):
        # A failing enricher should log a warning, not propagate the exception.
        try:
            enrich(self.catalogue, enrichers=[_enricher_raises])
        except RuntimeError:
            self.fail("enrich() should not propagate enricher exceptions")

    def test_failing_enricher_other_enrichers_still_run(self):
        enrich(self.catalogue, enrichers=[_enricher_raises, _enricher_constant])
        item = self._get_mu_item()
        self.assertIn("test_prop", item.properties)

    def test_multiple_enrichers_applied(self):
        enrich(self.catalogue, enrichers=[_enricher_constant, _enricher_two_keys])
        item = self._get_mu_item()
        self.assertIn("test_prop", item.properties)
        self.assertIn("key_a", item.properties)

    def test_event_collections_are_skipped(self):
        # Properties must not appear on event items.
        enrich(self.catalogue, enrichers=[_enricher_constant])
        from eomatch.domain import MATCHUP_EVENTS_COLLECTION_PREFIX

        for col in self.catalogue.catalog.get_children():
            if not col.id.startswith(f"{MATCHUP_EVENTS_COLLECTION_PREFIX}-"):
                continue
            for item in col.get_items():
                self.assertNotIn("test_prop", item.properties)

    def test_product_collections_are_skipped(self):
        # Properties must not appear on product items (LANDSAT_C2L1, S3_EFR).
        enrich(self.catalogue, enrichers=[_enricher_constant])
        for col_id in ("LANDSAT_C2L1", "S3_EFR"):
            col = self.catalogue.catalog.get_child(col_id)
            if col is None:
                continue
            for item in col.get_items():
                self.assertNotIn("test_prop", item.properties)

    def test_saves_to_disk_when_self_href_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.catalogue.save(tmpdir)
            # Re-open so items have self_hrefs pointing to real files.
            saved = MatchupCatalogue.open(tmpdir)
            enrich(saved, enrichers=[_enricher_constant])

            # Verify the JSON on disk was updated.
            from eomatch.domain import MATCHUP_EVENTS_COLLECTION_PREFIX

            prefix = f"{MATCHUP_EVENTS_COLLECTION_PREFIX}-"
            for col in saved.catalog.get_children():
                if col.id.startswith(prefix) or "-vs-" not in col.id:
                    continue
                for item in col.get_items():
                    with open(item.get_self_href()) as fh:
                        data = json.load(fh)
                    self.assertEqual(data["properties"].get("test_prop"), 42)


# ---------------------------------------------------------------------------
# Tests for _load_enricher
# ---------------------------------------------------------------------------


class TestLoadEnricher(unittest.TestCase):
    def test_loads_builtin_enricher(self):
        from eomatch.enrich.time_diff import time_diff

        fn = _load_enricher("eomatch.enrich.time_diff.time_diff")
        self.assertIs(fn, time_diff)

    def test_raises_import_error_on_missing_module(self):
        with self.assertRaises(ImportError):
            _load_enricher("eomatch.enrich.nonexistent_module.fn")

    def test_raises_attribute_error_on_missing_function(self):
        with self.assertRaises(AttributeError):
            _load_enricher("eomatch.enrich.time_diff.no_such_function")

    def test_raises_value_error_with_no_module_component(self):
        with self.assertRaises(ValueError):
            _load_enricher("bare_name")


if __name__ == "__main__":
    unittest.main()
