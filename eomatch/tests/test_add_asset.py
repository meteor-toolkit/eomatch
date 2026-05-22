"""eomatch.tests.test_add_asset - tests for register_analysis and add_asset_by_id"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pystac
from shapely.geometry import Polygon, mapping

from eomatch.add_asset import _detect_media_type, main, register_analysis
from eomatch.domain import Matchup, MatchupEvent, MatchupSet
from eomatch.mu_stac import MatchupCatalogue

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = []

# ---------------------------------------------------------------------------
# Shared fixtures (mirror test_mu_stac.py helpers)
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
        (-34.5322, 153.097),
        (-33.3857, 147.276),
        (-45.0568, 150.247),
    ]
)

L8_START = dt.datetime(2022, 6, 7, 23, 38, 55, 976000)
L8_STOP = dt.datetime(2022, 6, 7, 23, 39, 23, 976000)
S3_START = dt.datetime(2022, 6, 7, 23, 38, 58, 833000)
S3_STOP = dt.datetime(2022, 6, 7, 23, 41, 57, 833000)

L8_STAC_ID = "LC08_L1GT_089087_20220607_20220616_02_T2"
S3_STAC_ID = "S3A_OL_1_EFR____20220607T233858_20220607T234158_20220608T234813_0180_086_144_3600_PS1_O_NT_002"

MATCHUP_COLLECTION_ID = "LANDSAT_C2L1-Landsat-vs-S3_EFR-Sentinel-3"


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


L8_PRODUCT = _make_mock_product("Landsat", "LANDSAT_C2L1", L8_STAC_ID, L8_GEOMETRY, L8_START, L8_STOP)
S3_PRODUCT = _make_mock_product("Sentinel-3", "S3_EFR", S3_STAC_ID, S3_GEOMETRY, S3_START, S3_STOP)


def _make_matchup():
    return Matchup(_FakeProductItemSet([L8_PRODUCT, S3_PRODUCT]))


def _make_populated_catalogue() -> tuple[MatchupCatalogue, Matchup]:
    cat = MatchupCatalogue()
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
    mu = _make_matchup()
    event.matchup_set = MatchupSet([mu])
    cat.add_event(event)
    return cat, mu


# ---------------------------------------------------------------------------
# _detect_media_type
# ---------------------------------------------------------------------------


class TestDetectMediaType(unittest.TestCase):
    def test_netcdf(self):
        self.assertEqual(_detect_media_type("result.nc"), "application/x-netcdf")

    def test_tiff(self):
        self.assertEqual(_detect_media_type("image.tif"), "image/tiff")
        self.assertEqual(_detect_media_type("image.tiff"), "image/tiff")

    def test_json(self):
        self.assertEqual(_detect_media_type("data.json"), "application/json")

    def test_csv(self):
        self.assertEqual(_detect_media_type("data.csv"), "text/csv")

    def test_unknown_falls_back(self):
        self.assertEqual(_detect_media_type("archive.xyz"), "application/octet-stream")

    def test_case_insensitive(self):
        self.assertEqual(_detect_media_type("IMAGE.NC"), "application/x-netcdf")


# ---------------------------------------------------------------------------
# add_asset_by_id (MatchupCatalogue method)
# ---------------------------------------------------------------------------


class TestAddAssetById(unittest.TestCase):
    def setUp(self):
        self.catalogue, self.mu = _make_populated_catalogue()
        self.asset = pystac.Asset(href="/tmp/result.nc", media_type="application/x-netcdf")

    def test_returns_true_for_known_item(self):
        mu_item_id = self.mu.stac_id
        self.assertTrue(self.catalogue.add_asset_by_id(MATCHUP_COLLECTION_ID, mu_item_id, "test:key", self.asset))

    def test_asset_present_after_add(self):
        mu_item_id = self.mu.stac_id
        self.catalogue.add_asset_by_id(MATCHUP_COLLECTION_ID, mu_item_id, "test:key", self.asset)
        col = self.catalogue.catalog.get_child(MATCHUP_COLLECTION_ID)
        item = next(col.get_items(mu_item_id))
        self.assertIn("test:key", item.assets)

    def test_returns_false_for_unknown_collection(self):
        self.assertFalse(self.catalogue.add_asset_by_id("NO_SUCH_COL", self.mu.stac_id, "k", self.asset))

    def test_returns_false_for_unknown_item(self):
        self.assertFalse(self.catalogue.add_asset_by_id(MATCHUP_COLLECTION_ID, "no-such-item", "k", self.asset))


# ---------------------------------------------------------------------------
# register_analysis
# ---------------------------------------------------------------------------


class TestRegisterAnalysis(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        catalogue, self.mu = _make_populated_catalogue()
        catalogue.save(self.tmp_dir)
        self.collection_id = MATCHUP_COLLECTION_ID
        self.item_id = self.mu.stac_id
        # Create a dummy analysis file
        self.nc_file = os.path.join(self.tmp_dir, "comparison.nc")
        with open(self.nc_file, "w") as fh:
            fh.write("dummy")

    def _get_item(self) -> pystac.Item:
        cat = MatchupCatalogue.open(self.tmp_dir)
        col = cat.catalog.get_child(self.collection_id)
        assert col is not None
        return next(col.get_items(self.item_id))

    def test_dated_key_created(self):
        today = dt.date(2026, 5, 12)
        register_analysis(self.tmp_dir, self.collection_id, self.item_id, self.nc_file, date=today)
        item = self._get_item()
        self.assertIn("comparison:2026-05-12", item.assets)

    def test_latest_key_created(self):
        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            self.nc_file,
            date=dt.date(2026, 5, 12),
        )
        item = self._get_item()
        self.assertIn("comparison:latest", item.assets)

    def test_both_keys_point_to_same_href(self):
        today = dt.date(2026, 5, 12)
        register_analysis(self.tmp_dir, self.collection_id, self.item_id, self.nc_file, date=today)
        item = self._get_item()
        self.assertEqual(
            item.assets["comparison:2026-05-12"].href,
            item.assets["comparison:latest"].href,
        )

    def test_custom_key_prefix(self):
        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            self.nc_file,
            key_prefix="validation",
            date=dt.date(2026, 5, 12),
        )
        item = self._get_item()
        self.assertIn("validation:2026-05-12", item.assets)
        self.assertIn("validation:latest", item.assets)

    def test_media_type_auto_detected(self):
        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            self.nc_file,
            date=dt.date(2026, 5, 12),
        )
        item = self._get_item()
        self.assertEqual(item.assets["comparison:latest"].media_type, "application/x-netcdf")

    def test_explicit_media_type_used(self):
        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            self.nc_file,
            date=dt.date(2026, 5, 12),
            media_type="application/octet-stream",
        )
        item = self._get_item()
        self.assertEqual(item.assets["comparison:latest"].media_type, "application/octet-stream")

    def test_title_defaults_to_filename(self):
        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            self.nc_file,
            date=dt.date(2026, 5, 12),
        )
        item = self._get_item()
        self.assertEqual(item.assets["comparison:latest"].title, "comparison.nc")

    def test_explicit_title_used(self):
        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            self.nc_file,
            date=dt.date(2026, 5, 12),
            title="My comparison",
        )
        item = self._get_item()
        self.assertEqual(item.assets["comparison:latest"].title, "My comparison")

    def test_latest_overwritten_on_second_run(self):
        nc_v1 = os.path.join(self.tmp_dir, "comparison_v1.nc")
        nc_v2 = os.path.join(self.tmp_dir, "comparison_v2.nc")
        for p in (nc_v1, nc_v2):
            with open(p, "w") as fh:
                fh.write("dummy")

        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            nc_v1,
            date=dt.date(2026, 5, 11),
        )
        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            nc_v2,
            date=dt.date(2026, 5, 12),
        )
        item = self._get_item()
        # Dated snapshots for both dates present
        self.assertIn("comparison:2026-05-11", item.assets)
        self.assertIn("comparison:2026-05-12", item.assets)
        # Latest points at the most recent file
        self.assertEqual(item.assets["comparison:latest"].href, nc_v2)

    def test_unknown_item_raises(self):
        with self.assertRaises(ValueError):
            register_analysis(self.tmp_dir, self.collection_id, "no-such-item", self.nc_file)

    def test_unknown_collection_raises(self):
        with self.assertRaises(ValueError):
            register_analysis(self.tmp_dir, "NO_SUCH_COL", self.item_id, self.nc_file)

    def test_persisted_to_disk(self):
        register_analysis(
            self.tmp_dir,
            self.collection_id,
            self.item_id,
            self.nc_file,
            date=dt.date(2026, 5, 12),
        )
        # Re-open from disk and verify the asset survived round-trip
        item = self._get_item()
        self.assertIn("comparison:latest", item.assets)


# ---------------------------------------------------------------------------
# register_analysis — push=True path
# ---------------------------------------------------------------------------


class TestRegisterAnalysisPush(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        catalogue, self.mu = _make_populated_catalogue()
        catalogue.save(self.tmp_dir)
        self.collection_id = MATCHUP_COLLECTION_ID
        self.item_id = self.mu.stac_id
        self.nc_file = os.path.join(self.tmp_dir, "comparison.nc")
        with open(self.nc_file, "w") as fh:
            fh.write("dummy")

    def test_push_false_does_not_call_push_item(self):
        with patch("eomatch.add_asset._push_item") as mock_push:
            register_analysis(
                self.tmp_dir,
                self.collection_id,
                self.item_id,
                self.nc_file,
                date=dt.date(2026, 5, 12),
                push=False,
            )
            mock_push.assert_not_called()

    def test_push_true_calls_push_item(self):
        with patch("eomatch.add_asset._push_item") as mock_push:
            register_analysis(
                self.tmp_dir,
                self.collection_id,
                self.item_id,
                self.nc_file,
                date=dt.date(2026, 5, 12),
                push=True,
                db_host="localhost",
            )
            mock_push.assert_called_once()

    def test_push_item_receives_correct_collection_and_item(self):
        with patch("eomatch.add_asset._push_item") as mock_push:
            register_analysis(
                self.tmp_dir,
                self.collection_id,
                self.item_id,
                self.nc_file,
                date=dt.date(2026, 5, 12),
                push=True,
            )
            args = mock_push.call_args[0]
            self.assertEqual(args[1], self.collection_id)
            self.assertEqual(args[2], self.item_id)


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


class TestMain(unittest.TestCase):
    def _run_main(self, argv):
        with patch("sys.argv", ["eomatch-add-asset"] + argv):
            with patch("eomatch.add_asset.register_analysis") as mock_reg:
                main()
                return mock_reg

    def test_required_args_passed_to_register_analysis(self):
        mock_reg = self._run_main(
            [
                "--catalogue",
                "/tmp/cat",
                "--collection-id",
                "MY_COL",
                "--item-id",
                "MY_ITEM",
                "--file",
                "/tmp/result.nc",
            ]
        )
        mock_reg.assert_called_once()
        kw = mock_reg.call_args.kwargs
        self.assertEqual(kw["catalogue_path"], "/tmp/cat")
        self.assertEqual(kw["collection_id"], "MY_COL")
        self.assertEqual(kw["item_id"], "MY_ITEM")
        self.assertEqual(kw["file_path"], "/tmp/result.nc")

    def test_missing_required_arg_exits(self):
        with self.assertRaises(SystemExit):
            with patch("sys.argv", ["eomatch-add-asset", "--catalogue", "/tmp/cat"]):
                main()

    def test_date_iso_parsed(self):
        mock_reg = self._run_main(
            [
                "--catalogue",
                "/tmp/cat",
                "--collection-id",
                "C",
                "--item-id",
                "I",
                "--file",
                "/tmp/f.nc",
                "--date",
                "2026-05-12",
            ]
        )
        self.assertEqual(mock_reg.call_args.kwargs["date"], dt.date(2026, 5, 12))

    def test_no_date_passes_none(self):
        mock_reg = self._run_main(
            [
                "--catalogue",
                "/tmp/cat",
                "--collection-id",
                "C",
                "--item-id",
                "I",
                "--file",
                "/tmp/f.nc",
            ]
        )
        self.assertIsNone(mock_reg.call_args.kwargs["date"])

    def test_push_flag(self):
        mock_reg = self._run_main(
            [
                "--catalogue",
                "/tmp/cat",
                "--collection-id",
                "C",
                "--item-id",
                "I",
                "--file",
                "/tmp/f.nc",
                "--push",
            ]
        )
        self.assertTrue(mock_reg.call_args.kwargs["push"])

    def test_push_false_by_default(self):
        mock_reg = self._run_main(
            [
                "--catalogue",
                "/tmp/cat",
                "--collection-id",
                "C",
                "--item-id",
                "I",
                "--file",
                "/tmp/f.nc",
            ]
        )
        self.assertFalse(mock_reg.call_args.kwargs["push"])

    def test_custom_key_prefix(self):
        mock_reg = self._run_main(
            [
                "--catalogue",
                "/tmp/cat",
                "--collection-id",
                "C",
                "--item-id",
                "I",
                "--file",
                "/tmp/f.nc",
                "--key-prefix",
                "validation",
            ]
        )
        self.assertEqual(mock_reg.call_args.kwargs["key_prefix"], "validation")

    def test_db_args_forwarded(self):
        mock_reg = self._run_main(
            [
                "--catalogue",
                "/tmp/cat",
                "--collection-id",
                "C",
                "--item-id",
                "I",
                "--file",
                "/tmp/f.nc",
                "--db-host",
                "myhost",
                "--db-port",
                "5433",
                "--db-name",
                "mydb",
            ]
        )
        kw = mock_reg.call_args.kwargs
        self.assertEqual(kw["db_host"], "myhost")
        self.assertEqual(kw["db_port"], 5433)
        self.assertEqual(kw["db_name"], "mydb")


if __name__ == "__main__":
    unittest.main()
