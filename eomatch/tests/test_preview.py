"""eomatch.tests.test_preview - tests for event thumbnail generation."""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import matplotlib

matplotlib.use("Agg")
import matplotlib.figure
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import Polygon

import xarray as xr
from scrappi import ProductItem, ProductItemSet
from eomatch.domain import Matchup, MatchupEvent, MatchupSet
from eomatch.preview import (
    BuildMUPreview,
    build_event_geo_thumbnail,
    build_geo_thumbnail,
    preview_event,
    preview_matchup,
)

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = []


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_S2_GEOM = Polygon(
    [
        (10.0, 50.0),
        (11.0, 50.0),
        (11.0, 51.0),
        (10.0, 51.0),
        (10.0, 50.0),
    ]
)

_LS_GEOM = Polygon(
    [
        (10.3, 50.2),
        (11.3, 50.2),
        (11.3, 51.2),
        (10.3, 51.2),
        (10.3, 50.2),
    ]
)

_S2_PRODUCT = ProductItem(
    constellation="Sentinel-2",
    platform="S2A",
    collection="S2_MSI_L1C",
    id="S2A_MSIL1C_20220607T100000",
    geometry=_S2_GEOM,
    start_time=dt.datetime(2022, 6, 7, 10, 0, 0),
    stop_time=dt.datetime(2022, 6, 7, 10, 5, 0),
)

_LS_PRODUCT = ProductItem(
    constellation="Landsat",
    platform="Landsat-9",
    collection="LANDSAT_C2L1",
    id="LC09_L1GT_089087_20220607",
    geometry=_LS_GEOM,
    start_time=dt.datetime(2022, 6, 7, 10, 0, 0),
    stop_time=dt.datetime(2022, 6, 7, 10, 5, 0),
)


def _make_event() -> MatchupEvent:
    """Return a MatchupEvent with a single two-product matchup attached."""
    event = MatchupEvent(
        collections=["S2_MSI_L1C", "LANDSAT_C2L1"],
        platforms=["S2A", "Landsat-9"],
        start_time=dt.datetime(2022, 6, 7, 10, 0, 0),
        stop_time=dt.datetime(2022, 6, 7, 10, 10, 0),
        latitude_minimum=49.5,
        longitude_minimum=9.5,
        latitude_maximum=51.5,
        longitude_maximum=11.5,
    )
    products = ProductItemSet([_S2_PRODUCT, _LS_PRODUCT])
    matchup = Matchup(products)
    ms = MatchupSet([matchup])
    event.matchup_set = ms
    return event


# ---------------------------------------------------------------------------
# Tests for build_event_geo_thumbnail
# ---------------------------------------------------------------------------


class TestBuildEventGeoThumbnail(unittest.TestCase):
    def test_creates_geotiff_file(self):
        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            self.assertTrue(os.path.exists(out))

    def test_output_is_rgba_geotiff(self):
        import rasterio

        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            with rasterio.open(out) as src:
                self.assertEqual(src.count, 4)
                self.assertEqual(src.dtypes[0], "uint8")

    def test_output_crs_is_wgs84(self):
        import rasterio
        from rasterio.crs import CRS

        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            with rasterio.open(out) as src:
                self.assertEqual(src.crs, CRS.from_epsg(4326))

    def test_output_bounds_match_event_bbox(self):
        import rasterio

        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            with rasterio.open(out) as src:
                b = src.bounds
                self.assertAlmostEqual(b.left, 9.5, places=5)
                self.assertAlmostEqual(b.bottom, 49.5, places=5)
                self.assertAlmostEqual(b.right, 11.5, places=5)
                self.assertAlmostEqual(b.top, 51.5, places=5)

    def test_polygons_have_nonzero_alpha(self):
        import rasterio

        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            with rasterio.open(out) as src:
                alpha = src.read(4)
                # At least some pixels should be non-transparent
                self.assertGreater(np.count_nonzero(alpha), 0)

    def test_background_is_transparent(self):
        import rasterio

        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            with rasterio.open(out) as src:
                alpha = src.read(4)
                # Background pixels (alpha==0) must exist since polygons don't
                # cover the entire bounding box
                self.assertGreater(np.count_nonzero(alpha == 0), 0)

    def test_fill_alpha_value(self):
        import rasterio

        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            with rasterio.open(out) as src:
                alpha = src.read(4)
                filled = alpha[alpha > 0]
                # All non-transparent pixels should have alpha == 180
                self.assertTrue(np.all(filled == 180))

    def test_two_collections_get_different_colours(self):
        import rasterio

        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            with rasterio.open(out) as src:
                r = src.read(1)
                g = src.read(2)
                b = src.read(3)
                alpha = src.read(4)
                # Collect unique RGB tuples for filled pixels
                mask = alpha > 0
                colors = set(zip(r[mask].tolist(), g[mask].tolist(), b[mask].tolist()))
                # Two different collections → at least two different colours
                self.assertGreaterEqual(len(colors), 2)

    def test_max_pixels_respected(self):
        import rasterio

        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out, max_pixels=64)
            with rasterio.open(out) as src:
                self.assertLessEqual(max(src.width, src.height), 64)

    def test_output_directory_created(self):
        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "nested", "dir", "event.tif")
            build_event_geo_thumbnail(event, out)
            self.assertTrue(os.path.exists(out))

    def test_raises_when_no_matchup_set(self):
        event = MatchupEvent(
            collections=["S2_MSI_L1C", "LANDSAT_C2L1"],
            platforms=["S2A", "Landsat-9"],
            start_time=dt.datetime(2022, 6, 7, 10, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 10, 10, 0),
            latitude_minimum=49.5,
            longitude_minimum=9.5,
            latitude_maximum=51.5,
            longitude_maximum=11.5,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                build_event_geo_thumbnail(event, os.path.join(tmpdir, "out.tif"))

    def test_deduplicates_products_across_matchups(self):
        """Products shared across matchups should only be rasterized once."""
        import rasterio

        event = _make_event()
        # Add a second matchup with the same products
        products2 = ProductItemSet([_S2_PRODUCT, _LS_PRODUCT])
        matchup2 = Matchup(products2)
        event.matchup_set.append(matchup2)

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event.tif")
            build_event_geo_thumbnail(event, out)
            with rasterio.open(out) as src:
                alpha = src.read(4)
                # Should not raise; alpha values should still be 0 or 180
                unique_alpha = set(np.unique(alpha))
                self.assertTrue(unique_alpha.issubset({0, 180}))


# ---------------------------------------------------------------------------
# Tests for preview_event
# ---------------------------------------------------------------------------


class TestPreviewEvent(unittest.TestCase):
    @patch("eomatch.domain.MatchupEvent.plot")
    def test_returns_figure(self, mock_plot):
        event = _make_event()
        fig = preview_event(event)
        plt.close(fig)
        self.assertIsInstance(fig, matplotlib.figure.Figure)

    @patch("eomatch.domain.MatchupEvent.plot")
    def test_saves_file_when_output_path_given(self, mock_plot):
        event = _make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "event_thumb.png")
            fig = preview_event(event, output_path=out)
            plt.close(fig)
            self.assertTrue(os.path.exists(out))

    @patch("eomatch.domain.MatchupEvent.plot")
    def test_no_file_without_output_path(self, mock_plot):
        event = _make_event()
        fig = preview_event(event)
        plt.close(fig)
        # Just verify no unintended side-effects; test passes if no exception

    def test_raises_when_no_matchup_set(self):
        event = MatchupEvent(
            collections=["S2_MSI_L1C", "LANDSAT_C2L1"],
            platforms=["S2A", "Landsat-9"],
            start_time=dt.datetime(2022, 6, 7, 10, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 10, 10, 0),
            latitude_minimum=49.5,
            longitude_minimum=9.5,
            latitude_maximum=51.5,
            longitude_maximum=11.5,
        )
        with self.assertRaises(ValueError):
            preview_event(event)

    @patch("eomatch.domain.MatchupEvent.plot")
    def test_raises_when_empty_matchup_set(self, mock_plot):
        event = MatchupEvent(
            collections=["S2_MSI_L1C", "LANDSAT_C2L1"],
            platforms=["S2A", "Landsat-9"],
            start_time=dt.datetime(2022, 6, 7, 10, 0, 0),
            stop_time=dt.datetime(2022, 6, 7, 10, 10, 0),
            latitude_minimum=49.5,
            longitude_minimum=9.5,
            latitude_maximum=51.5,
            longitude_maximum=11.5,
        )
        event.matchup_set = MatchupSet([])
        with self.assertRaises(ValueError):
            preview_event(event)

    @patch("eomatch.domain.MatchupEvent.plot")
    def test_event_plot_called_with_axes(self, mock_plot):
        event = _make_event()
        fig = preview_event(event)
        plt.close(fig)
        mock_plot.assert_called_once()
        _, kwargs = mock_plot.call_args
        self.assertIn("ax", kwargs)


# ---------------------------------------------------------------------------
# Helper for creating lightweight in-memory datasets
# ---------------------------------------------------------------------------


def _make_dataset(n_bands: int = 3, shape: tuple = (20, 20), collection: str = "TEST") -> xr.Dataset:
    """Return a minimal xr.Dataset with ``n_bands`` float32 bands and meas_vars set."""
    rng = np.random.default_rng(0)
    data = {f"b{i}": xr.DataArray(rng.random(shape).astype(np.float32), dims=["y", "x"]) for i in range(n_bands)}
    ds = xr.Dataset(data)
    ds.attrs["meas_vars"] = list(data.keys())
    ds.attrs["collection"] = collection
    return ds


# ---------------------------------------------------------------------------
# BuildMUPreview.__init__
# ---------------------------------------------------------------------------


class TestBuildMUPreviewInit(unittest.TestCase):
    def test_default_context_is_eomatch_context(self):
        from eomatch.context import EOMatchContext

        builder = BuildMUPreview()
        self.assertIsInstance(builder.context, EOMatchContext)

    def test_explicit_context_stored(self):
        mock_ctx = MagicMock()
        builder = BuildMUPreview(context=mock_ctx)
        self.assertIs(builder.context, mock_ctx)


# ---------------------------------------------------------------------------
# BuildMUPreview._resolve_preview_read_kwargs
# ---------------------------------------------------------------------------


class TestResolvePreviewReadKwargs(unittest.TestCase):
    def _builder(self, preview_cfg=None):
        ctx = MagicMock()
        ctx.get.return_value = preview_cfg
        return BuildMUPreview(context=ctx)

    def test_fallback_defaults_when_no_config(self):
        builder = self._builder(None)
        vars_sel, read_params, processors = builder._resolve_preview_read_kwargs("ANY", None)
        self.assertEqual(vars_sel["meas"], "rgb")
        self.assertFalse(read_params["metadata_level"])
        self.assertEqual(processors, {})

    def test_global_defaults_override_fallbacks(self):
        builder = self._builder(
            {
                "read": {
                    "defaults": {
                        "vars_sel": {"meas": "all", "aux": []},
                        "read_params": {"metadata_level": True},
                    }
                }
            }
        )
        vars_sel, read_params, _ = builder._resolve_preview_read_kwargs("ANY", None)
        self.assertEqual(vars_sel["meas"], "all")
        self.assertTrue(read_params["metadata_level"])

    def test_collection_cfg_overrides_global(self):
        builder = self._builder(
            {
                "read": {
                    "defaults": {"vars_sel": {"meas": "all", "aux": []}},
                    "collections": {"MY_COL": {"vars_sel": {"meas": "rgb", "aux": []}}},
                }
            }
        )
        vars_sel, _, _ = builder._resolve_preview_read_kwargs("MY_COL", None)
        self.assertEqual(vars_sel["meas"], "rgb")

    def test_call_level_vars_sel_replaces_entirely(self):
        builder = self._builder(None)
        call_args = {"MY_COL": {"vars_sel": {"meas": "custom"}}}
        vars_sel, _, _ = builder._resolve_preview_read_kwargs("MY_COL", call_args)
        self.assertEqual(vars_sel["meas"], "custom")

    def test_call_level_read_params_merges(self):
        builder = self._builder(None)
        call_args = {"MY_COL": {"read_params": {"use_chunks": True}}}
        _, read_params, _ = builder._resolve_preview_read_kwargs("MY_COL", call_args)
        self.assertTrue(read_params["use_chunks"])
        # Fallback keys not in the override are preserved
        self.assertFalse(read_params["metadata_level"])

    def test_unknown_collection_uses_global_defaults(self):
        builder = self._builder(
            {
                "read": {
                    "defaults": {"vars_sel": {"meas": "all", "aux": []}},
                    "collections": {"OTHER_COL": {"vars_sel": {"meas": "rgb", "aux": []}}},
                }
            }
        )
        vars_sel, _, _ = builder._resolve_preview_read_kwargs("UNKNOWN", None)
        self.assertEqual(vars_sel["meas"], "all")


# ---------------------------------------------------------------------------
# BuildMUPreview._resize_array
# ---------------------------------------------------------------------------


class TestResizeArray(unittest.TestCase):
    def test_array_within_limit_returned_unchanged(self):
        arr = np.ones((10, 10), dtype=np.float32)
        result = BuildMUPreview._resize_array(arr, max_pixels=512)
        self.assertEqual(result.shape, (10, 10))

    def test_large_array_downsampled(self):
        arr = np.ones((800, 800), dtype=np.float32)
        result = BuildMUPreview._resize_array(arr, max_pixels=64)
        self.assertLessEqual(max(result.shape), 64)

    def test_aspect_ratio_approximately_preserved(self):
        arr = np.ones((800, 400), dtype=np.float32)
        result = BuildMUPreview._resize_array(arr, max_pixels=100)
        self.assertEqual(result.shape[0], 100)
        self.assertAlmostEqual(result.shape[1] / result.shape[0], 400 / 800, delta=0.05)

    def test_min_size_is_one_pixel(self):
        arr = np.ones((1000, 1000), dtype=np.float32)
        result = BuildMUPreview._resize_array(arr, max_pixels=1)
        self.assertEqual(result.shape, (1, 1))


# ---------------------------------------------------------------------------
# BuildMUPreview._normalise_to_uint8
# ---------------------------------------------------------------------------


class TestNormaliseToUint8(unittest.TestCase):
    def test_output_dtype(self):
        rgb = np.random.default_rng(0).random((10, 10, 3)).astype(np.float32)
        result = BuildMUPreview._normalise_to_uint8(rgb)
        self.assertEqual(result.dtype, np.uint8)

    def test_output_in_range_0_255(self):
        rgb = np.random.default_rng(0).random((20, 20, 3)).astype(np.float32)
        result = BuildMUPreview._normalise_to_uint8(rgb)
        self.assertGreaterEqual(int(result.min()), 0)
        self.assertLessEqual(int(result.max()), 255)

    def test_uniform_channel_gives_zeros(self):
        rgb = np.ones((10, 10, 3), dtype=np.float32)
        result = BuildMUPreview._normalise_to_uint8(rgb)
        self.assertTrue(np.all(result == 0))

    def test_all_nan_gives_zeros(self):
        rgb = np.full((10, 10, 3), np.nan, dtype=np.float32)
        result = BuildMUPreview._normalise_to_uint8(rgb)
        self.assertTrue(np.all(result == 0))

    def test_shape_preserved(self):
        rgb = np.random.default_rng(0).random((8, 12, 3)).astype(np.float32)
        result = BuildMUPreview._normalise_to_uint8(rgb)
        self.assertEqual(result.shape, (8, 12, 3))


# ---------------------------------------------------------------------------
# BuildMUPreview._ds_to_rgb_array
# ---------------------------------------------------------------------------


class TestDsToRgbArray(unittest.TestCase):
    def test_three_band_returns_hwc_shape(self):
        builder = BuildMUPreview()
        result = builder._ds_to_rgb_array(_make_dataset(n_bands=3, shape=(20, 20)), max_pixels=512)
        self.assertEqual(result.shape, (20, 20, 3))

    def test_one_band_replicates_to_greyscale(self):
        builder = BuildMUPreview()
        result = builder._ds_to_rgb_array(_make_dataset(n_bands=1, shape=(20, 20)), max_pixels=512)
        self.assertEqual(result.shape, (20, 20, 3))
        np.testing.assert_array_equal(result[:, :, 0], result[:, :, 1])
        np.testing.assert_array_equal(result[:, :, 1], result[:, :, 2])

    def test_max_pixels_applied(self):
        builder = BuildMUPreview()
        result = builder._ds_to_rgb_array(_make_dataset(n_bands=1, shape=(200, 200)), max_pixels=32)
        self.assertLessEqual(max(result.shape[:2]), 32)

    def test_output_dtype_is_uint8(self):
        builder = BuildMUPreview()
        result = builder._ds_to_rgb_array(_make_dataset(n_bands=3), max_pixels=512)
        self.assertEqual(result.dtype, np.uint8)

    def test_empty_meas_vars_raises(self):
        builder = BuildMUPreview()
        ds = xr.Dataset()
        ds.attrs["meas_vars"] = []
        with self.assertRaises(ValueError):
            builder._ds_to_rgb_array(ds, max_pixels=512)

    def test_extra_dims_squeezed(self):
        # Dataset with a leading time dimension
        builder = BuildMUPreview()
        arr = np.random.default_rng(0).random((1, 20, 20)).astype(np.float32)
        ds = xr.Dataset({"b0": xr.DataArray(arr, dims=["time", "y", "x"])})
        ds.attrs["meas_vars"] = ["b0"]
        result = builder._ds_to_rgb_array(ds, max_pixels=512)
        self.assertEqual(result.shape, (20, 20, 3))


# ---------------------------------------------------------------------------
# BuildMUPreview._make_figure
# ---------------------------------------------------------------------------


class TestMakeFigure(unittest.TestCase):
    def test_returns_figure(self):
        builder = BuildMUPreview()
        fig = builder._make_figure([_make_dataset(), _make_dataset()], max_pixels=32)
        plt.close(fig)
        self.assertIsInstance(fig, matplotlib.figure.Figure)

    def test_one_axes_per_sensor(self):
        builder = BuildMUPreview()
        for n in (1, 2, 3):
            fig = builder._make_figure([_make_dataset() for _ in range(n)], max_pixels=32)
            plt.close(fig)
            self.assertEqual(len(fig.axes), n)

    def test_bad_dataset_renders_fallback_text(self):
        builder = BuildMUPreview()
        bad_ds = xr.Dataset()
        bad_ds.attrs["meas_vars"] = []
        bad_ds.attrs["collection"] = "BAD"
        # Should not raise — uses "No preview" fallback text
        fig = builder._make_figure([bad_ds], max_pixels=32)
        plt.close(fig)
        self.assertIsInstance(fig, matplotlib.figure.Figure)

    def test_collection_used_as_axis_title(self):
        builder = BuildMUPreview()
        ds = _make_dataset(collection="S2_MSI_L1C")
        fig = builder._make_figure([ds], max_pixels=32)
        plt.close(fig)
        self.assertEqual(fig.axes[0].get_title(), "S2_MSI_L1C")


# ---------------------------------------------------------------------------
# BuildMUPreview.run
# ---------------------------------------------------------------------------


class TestBuildMUPreviewRun(unittest.TestCase):
    def test_raises_when_products_none(self):
        builder = BuildMUPreview()
        mu = MagicMock()
        mu.products = None
        with self.assertRaises(ValueError):
            builder.run(mu)

    def test_returns_figure(self):
        builder = BuildMUPreview()
        mu = MagicMock()
        mu.products = MagicMock()
        mu.collocation_region = MagicMock()
        product_ds = [_make_dataset(), _make_dataset()]
        with patch.object(builder, "read_products", return_value=product_ds):
            fig = builder.run(mu, max_pixels=32)
        plt.close(fig)
        self.assertIsInstance(fig, matplotlib.figure.Figure)

    def test_saves_png_when_output_path_given(self):
        builder = BuildMUPreview()
        mu = MagicMock()
        mu.products = MagicMock()
        mu.collocation_region = MagicMock()
        product_ds = [_make_dataset(), _make_dataset()]
        with patch.object(builder, "read_products", return_value=product_ds):
            with tempfile.TemporaryDirectory() as tmpdir:
                out = os.path.join(tmpdir, "preview.png")
                fig = builder.run(mu, output_path=out, max_pixels=32)
                plt.close(fig)
                self.assertTrue(os.path.exists(out))


# ---------------------------------------------------------------------------
# Module-level wrappers: preview_matchup, build_geo_thumbnail
# ---------------------------------------------------------------------------


class TestPreviewMatchupWrapper(unittest.TestCase):
    def test_delegates_to_builder_run(self):
        mu = MagicMock()
        mock_fig = MagicMock(spec=matplotlib.figure.Figure)
        with patch("eomatch.preview.BuildMUPreview.run", return_value=mock_fig) as mock_run:
            result = preview_matchup(mu, max_pixels=64)
        self.assertIs(result, mock_fig)
        mock_run.assert_called_once()


class TestBuildGeoThumbnailWrapper(unittest.TestCase):
    def test_delegates_to_builder_build_geo_thumbnail(self):
        mu = MagicMock()
        with patch("eomatch.preview.BuildMUPreview.build_geo_thumbnail") as mock_method:
            build_geo_thumbnail(mu, "out.tif", max_pixels=64)
            mock_method.assert_called_once_with(
                matchup=mu,
                output_path="out.tif",
                collection_read_args=None,
                max_pixels=64,
            )


if __name__ == "__main__":
    unittest.main()
