"""eomatch.preview - utilities for generating matchup preview images"""

import logging
import os
from typing import TYPE_CHECKING, Optional

import numpy as np
import matplotlib.figure
import matplotlib.pyplot as plt
import shapely
import xarray as xr
from scrappi.product import ProductItemSet

from eomatch.context import EOMatchContext

if TYPE_CHECKING:
    from eomatch.domain import Matchup, MatchupEvent

logger = logging.getLogger(__name__)

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = [
    "BuildMUPreview",
    "preview_matchup",
    "build_geo_thumbnail",
    "preview_event",
    "build_event_geo_thumbnail",
]

_PREVIEW_FALLBACK_VARS_SEL = {"meas": "rgb", "aux": []}
_PREVIEW_FALLBACK_READ_PARAMS = {
    "use_chunks": False,
    "metadata_level": False,
    "save_extracted": False,
}
_PREVIEW_FALLBACK_PROCESSORS = {}
_DEFAULT_MAX_PIXELS = 512


class BuildMUPreview:
    """
    Utility class for generating side-by-side preview images from matchup objects.

    Reads each product with lightweight, preview-specific defaults (configured
    under ``preview.read`` in the context config) and renders one panel per
    sensor in a :py:class:`matplotlib.figure.Figure`.

    Example usage::

        from eomatch.preview import BuildMUPreview

        builder = BuildMUPreview()
        fig = builder.run(matchup)
        fig = builder.run(matchup, output_path="preview.png", max_pixels=256)
    """

    def __init__(self, context: Optional[EOMatchContext] = None) -> None:
        if context is None:
            self.context = EOMatchContext()
        else:
            self.context = context

    def run(
        self,
        matchup: "Matchup",
        output_path: Optional[str] = None,
        collection_read_args: Optional[dict] = None,
        max_pixels: int = _DEFAULT_MAX_PIXELS,
    ) -> matplotlib.figure.Figure:
        """
        Generate a side-by-side preview figure for a matchup.

        Reads each product using preview-optimised defaults (``meas: ["rgb"]``
        unless overridden), downsamples to at most ``max_pixels`` in each
        spatial dimension, and renders one panel per sensor.  If
        ``output_path`` is supplied the figure is also saved to disk.

        :param matchup: matchup object whose products will be previewed.
        :param output_path: optional path at which to save the figure.  Any
            format accepted by :py:func:`matplotlib.figure.Figure.savefig` is
            supported (e.g. ``"preview.png"``, ``"preview.pdf"``).
        :param collection_read_args: per-collection call-time overrides for
            ``vars_sel``, ``read_params``, and/or ``processors``.  Keyed by
            STAC collection ID; follows the same merge semantics as
            :py:meth:`eomatch.datatree.BuildMUDT._resolve_read_kwargs`.
        :param max_pixels: maximum pixel extent in either spatial dimension
            after post-read downsampling.  Smaller values produce lighter
            figures at the cost of detail.
        :return: matplotlib :py:class:`~matplotlib.figure.Figure` with one
            panel per sensor.
        """
        if matchup.products is None:
            raise ValueError("No products set in Matchup object")

        product_ds = self.read_products(
            matchup.products,
            matchup.collocation_region,
            collection_read_args=collection_read_args,
        )
        fig = self._make_figure(product_ds, max_pixels=max_pixels)

        if output_path is not None:
            fig.canvas.draw()
            fig.savefig(output_path, bbox_inches="tight", dpi=150, facecolor="white")
            logger.info("Preview saved to %s", output_path)

        return fig

    def _resolve_preview_read_kwargs(
        self,
        collection: str,
        collection_read_args: Optional[dict],
    ) -> tuple:
        """Resolve ``eoio.read`` kwargs for a single product using the
        ``preview.read`` config section.

        Follows the same four-level merge order as
        :py:meth:`eomatch.datatree.BuildMUDT._resolve_read_kwargs` but
        draws defaults from ``preview.read`` rather than ``read``, and uses
        lighter fallbacks suited to thumbnail generation
        (``meas: ["rgb"]``, ``metadata_level: false``).

        :param collection: STAC collection ID of the product being read.
        :param collection_read_args: per-collection call-time overrides.
        :return: resolved ``(vars_sel, read_params, processors)`` tuple.
        """
        preview_cfg = (self.context.get("preview") or {}) if self.context else {}
        read_cfg = (preview_cfg.get("read") or {}) if isinstance(preview_cfg, dict) else {}
        global_defaults = read_cfg.get("defaults") or {}
        collection_cfg = (read_cfg.get("collections") or {}).get(collection) or {}
        call_cfg = (collection_read_args or {}).get(collection) or {}

        vars_sel = {
            **_PREVIEW_FALLBACK_VARS_SEL,
            **global_defaults.get("vars_sel", {}),
            **collection_cfg.get("vars_sel", {}),
        }
        read_params = {
            **_PREVIEW_FALLBACK_READ_PARAMS,
            **global_defaults.get("read_params", {}),
            **collection_cfg.get("read_params", {}),
        }
        processors = {
            **_PREVIEW_FALLBACK_PROCESSORS,
            **global_defaults.get("processors", {}),
            **collection_cfg.get("processors", {}),
        }

        if "vars_sel" in call_cfg:
            vars_sel = call_cfg["vars_sel"]
        if "read_params" in call_cfg:
            read_params = {**read_params, **call_cfg["read_params"]}
        if "processors" in call_cfg:
            processors = call_cfg["processors"]

        return vars_sel, read_params, processors

    def read_products(
        self,
        product_item_set: ProductItemSet,
        roi: shapely.Polygon,
        download: bool = True,
        collection_read_args: Optional[dict] = None,
    ):
        """Open matchup products using preview-specific read defaults.

        :param product_item_set: products to open.
        :param roi: region of interest to clip to.
        :param download: if ``True`` download products before reading if they
            are not already present on disk.
        :param collection_read_args: per-collection call-time overrides.
        :return: list of per-sensor :py:class:`xarray.Dataset` objects.
        """
        from eoio import read

        product_ds = []
        for product in product_item_set:
            url = getattr(product, "url", "")
            if url and os.path.isabs(url):
                if os.path.exists(url):
                    path = url
                elif os.path.exists(url + ".tar.gz"):
                    path = url + ".tar.gz"
                else:
                    path = product.get_path()
                    if not os.path.exists(path) and download:
                        product.download_product()
            else:
                path = product.get_path()
                if not os.path.exists(path) and download:
                    product.download_product()

            _vars_sel, _read_params, _processors = self._resolve_preview_read_kwargs(
                collection=getattr(product, "collection", ""),
                collection_read_args=collection_read_args,
            )

            pds = read(
                path=path,
                vars_sel=_vars_sel,
                subset={"roi": roi, "roi_crs": 4326},
                read_params=_read_params,
                processors=_processors,
            )
            pds.attrs["collection"] = getattr(product, "collection", "")
            product_ds.append(pds)

        return product_ds

    def _ds_to_rgb_array(self, ds: xr.Dataset, max_pixels: int) -> np.ndarray:
        """Convert a product dataset to a ``uint8`` RGB array for display.

        Selects up to three bands from ``meas_vars``.  When three bands are
        present they are assumed to be in Blue-Green-Red order (as returned by
        the eoio ``"rgb"`` sentinel) and are reversed to form a natural-colour
        composite.  A single band is replicated to a greyscale triplet.

        :param ds: per-sensor dataset from :py:meth:`read_products`.
        :param max_pixels: maximum pixel extent in either spatial dimension
            after downsampling.
        :return: ``uint8`` NumPy array of shape ``(H, W, 3)``.
        """
        meas_vars = list(ds.attrs.get("meas_vars", list(ds.data_vars)))[:3]

        if not meas_vars:
            raise ValueError("Dataset has no measurement variables to preview")

        arrays = []
        for v in meas_vars:
            da = ds[v]
            # Squeeze any non-spatial leading dimensions (e.g. time)
            extra = [d for d in da.dims if not d.startswith(("x", "y"))]
            for dim in extra:
                da = da.isel({dim: 0}, drop=True)
            arrays.append(da.values.astype(np.float32))

        arrays = [self._resize_array(a, max_pixels) for a in arrays]

        if len(arrays) == 3:
            # eoio "rgb" sentinel returns bands in Blue-Green-Red order; reverse to get RGB
            rgb = np.stack(list(reversed(arrays)), axis=-1)
        else:
            arr = arrays[0]
            rgb = np.stack([arr, arr, arr], axis=-1)

        return self._normalise_to_uint8(rgb)

    @staticmethod
    def _resize_array(arr: np.ndarray, max_pixels: int) -> np.ndarray:
        """Downsample a 2-D array so neither dimension exceeds ``max_pixels``.

        Uses nearest-neighbour sampling via linear index spacing.

        :param arr: 2-D float array to resize.
        :param max_pixels: target maximum size in each dimension.
        :return: downsampled array.
        """
        h, w = arr.shape[0], arr.shape[1]
        if h <= max_pixels and w <= max_pixels:
            return arr
        scale = max_pixels / max(h, w)
        new_h = max(1, int(h * scale))
        new_w = max(1, int(w * scale))
        row_idx = np.round(np.linspace(0, h - 1, new_h)).astype(int)
        col_idx = np.round(np.linspace(0, w - 1, new_w)).astype(int)
        return arr[np.ix_(row_idx, col_idx)]

    @staticmethod
    def _normalise_to_uint8(rgb: np.ndarray) -> np.ndarray:
        """Stretch each channel to ``[0, 255]`` using 2nd–98th percentile clipping.

        :param rgb: float array of shape ``(H, W, 3)``.
        :return: ``uint8`` array of shape ``(H, W, 3)``.
        """
        out = np.zeros(rgb.shape, dtype=np.float32)
        for i in range(rgb.shape[-1]):
            band = rgb[..., i]
            finite = band[np.isfinite(band)]
            if finite.size == 0:
                continue
            lo, hi = np.percentile(finite, (2, 98))
            if hi > lo:
                out[..., i] = np.clip((band - lo) / (hi - lo), 0.0, 1.0)
        np.nan_to_num(out, copy=False, nan=0.0, posinf=1.0, neginf=0.0)
        return (out * 255).astype(np.uint8)

    def _ds_to_rgba_georef(self, ds: xr.Dataset) -> tuple:
        """Extract a uint8 RGBA array and spatial metadata from a product dataset.

        RGB bands are taken from ``meas_vars`` (up to three bands in BGR order,
        as returned by the eoio ``"rgb"`` sentinel), reversed to natural-colour
        order, normalised to uint8, and combined with an alpha channel that is
        opaque wherever all bands carry finite values.

        Requires the ``rioxarray`` ``.rio`` accessor to be registered.  It is
        imported lazily inside this method.

        :param ds: per-sensor dataset with rioxarray spatial metadata.
        :return: tuple of ``(rgba, transform, crs)`` where ``rgba`` is a uint8
            NumPy array of shape ``(4, H, W)``.
        """
        import rioxarray  # noqa: F401 — registers .rio accessor

        meas_vars = list(ds.attrs.get("meas_vars", list(ds.data_vars)))[:3]
        if not meas_vars:
            raise ValueError("Dataset has no measurement variables")

        arrays = []
        for v in meas_vars:
            da = ds[v]
            extra = [d for d in da.dims if not d.startswith(("x", "y"))]
            for dim in extra:
                da = da.isel({dim: 0}, drop=True)
            arrays.append(da)

        if len(arrays) == 3:
            arrays = list(reversed(arrays))  # BGR → RGB
        elif len(arrays) == 1:
            arrays = arrays * 3

        raw = np.stack([a.values.astype(np.float32) for a in arrays], axis=0)  # (3, H, W)

        # Alpha: opaque wherever all bands are finite
        valid = np.all(np.isfinite(raw), axis=0)
        alpha = (valid * 255).astype(np.uint8)

        # Normalise RGB to uint8; _normalise_to_uint8 expects (H, W, 3)
        rgb_uint8 = self._normalise_to_uint8(raw.transpose(1, 2, 0)).transpose(2, 0, 1)

        rgba = np.concatenate([rgb_uint8, alpha[np.newaxis]], axis=0)  # (4, H, W)

        return rgba, ds.rio.transform(), ds.rio.crs

    def build_geo_thumbnail(
        self,
        matchup: "Matchup",
        output_path: str,
        collection_read_args: Optional[dict] = None,
        max_pixels: int = _DEFAULT_MAX_PIXELS,
    ) -> None:
        """Generate a georeferenced RGBA GeoTIFF thumbnail for a matchup.

        Both tiles are reprojected onto a shared WGS84 (EPSG:4326) grid at
        reduced resolution.  The alpha channel is transparent outside all tile
        footprints so the base map remains visible in STAC Browser.  In
        overlap areas the second tile is drawn on top of the first.

        The output is a tiled, DEFLATE-compressed GeoTIFF with four bands
        (R, G, B, A).  Registering it under the ``"overview"`` asset role on
        the STAC Item causes STAC Browser to render it on the slippy map.

        Example usage::

            builder = BuildMUPreview()
            builder.build_geo_thumbnail(matchup, "overview.tif", max_pixels=512)

        :param matchup: matchup whose products will be composited.
        :param output_path: filesystem path at which to save the GeoTIFF.
        :param collection_read_args: per-collection read overrides (same
            semantics as :py:meth:`run`).
        :param max_pixels: maximum pixel count along the longer geographic
            axis of the output raster.
        """
        import rasterio
        from rasterio.crs import CRS
        from rasterio.transform import array_bounds, from_bounds
        from rasterio.warp import reproject as _reproject, Resampling, transform_bounds
        import rioxarray  # noqa: F401 — registers .rio accessor

        if matchup.products is None:
            raise ValueError("No products set in Matchup object")

        product_ds = self.read_products(
            matchup.products,
            matchup.collocation_region,
            collection_read_args=collection_read_args,
        )

        wgs84 = CRS.from_epsg(4326)

        # Extract RGBA + spatial metadata for each tile
        tiles = []
        for ds in product_ds:
            rgba, src_transform, src_crs = self._ds_to_rgba_georef(ds)
            h, w = rgba.shape[1], rgba.shape[2]
            native_bounds = array_bounds(h, w, src_transform)
            bounds_wgs84 = transform_bounds(src_crs, wgs84, *native_bounds)
            tiles.append((rgba, src_transform, src_crs, bounds_wgs84))

        if not tiles:
            raise ValueError("No tiles available to composite")

        # Union bounding box in WGS84
        west = min(t[3][0] for t in tiles)
        south = min(t[3][1] for t in tiles)
        east = max(t[3][2] for t in tiles)
        north = max(t[3][3] for t in tiles)

        # Output grid dimensions respecting geographic aspect ratio
        lon_span = east - west
        lat_span = north - south
        if lon_span >= lat_span:
            out_w = max_pixels
            out_h = max(1, round(max_pixels * lat_span / lon_span))
        else:
            out_h = max_pixels
            out_w = max(1, round(max_pixels * lon_span / lat_span))

        out_transform = from_bounds(west, south, east, north, out_w, out_h)
        canvas = np.zeros((4, out_h, out_w), dtype=np.uint8)

        # Warp each tile onto the canvas; later tiles overwrite in overlap areas
        for rgba, src_transform, src_crs, _ in tiles:
            warped = np.zeros((4, out_h, out_w), dtype=np.uint8)
            _reproject(
                source=rgba,
                destination=warped,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=out_transform,
                dst_crs=wgs84,
                resampling=Resampling.bilinear,
            )
            # Composite: overwrite canvas wherever this tile has coverage
            mask = warped[3] > 0
            canvas[:, mask] = warped[:, mask]

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        profile = {
            "driver": "GTiff",
            "dtype": "uint8",
            "width": out_w,
            "height": out_h,
            "count": 4,
            "crs": wgs84,
            "transform": out_transform,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(canvas)

        logger.info("Geo thumbnail saved to %s", output_path)

    def _make_figure(self, product_ds, max_pixels: int) -> matplotlib.figure.Figure:
        """Assemble a side-by-side matplotlib figure from per-sensor datasets.

        :param product_ds: list of per-sensor datasets from
            :py:meth:`read_products`.
        :param max_pixels: passed to :py:meth:`_ds_to_rgb_array` for
            downsampling.
        :return: matplotlib :py:class:`~matplotlib.figure.Figure`.
        """
        n = len(product_ds)
        fig, axes = plt.subplots(1, n, figsize=(5 * n, 5))
        if n == 1:
            axes = [axes]

        for i, (ax, ds) in enumerate(zip(axes, product_ds)):
            try:
                rgb = self._ds_to_rgb_array(ds, max_pixels)
                ax.imshow(rgb)
            except Exception as exc:
                logger.warning("Could not render sensor %d: %s", i + 1, exc)
                ax.text(
                    0.5,
                    0.5,
                    "No preview",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
            ax.set_title(ds.attrs.get("collection") or f"Sensor {i + 1}")
            ax.axis("off")

        fig.tight_layout()
        return fig


def preview_matchup(
    matchup: "Matchup",
    output_path: Optional[str] = None,
    collection_read_args: Optional[dict] = None,
    max_pixels: int = _DEFAULT_MAX_PIXELS,
    context: Optional[EOMatchContext] = None,
) -> matplotlib.figure.Figure:
    """Generate a side-by-side preview image for a matchup.

    Convenience wrapper around :py:class:`BuildMUPreview`.  Reads each product
    using preview-optimised defaults (see :py:class:`BuildMUPreview`) and
    returns a :py:class:`matplotlib.figure.Figure` with one panel per sensor.

    Example usage::

        from eomatch.preview import preview_matchup

        fig = preview_matchup(matchup)
        fig = preview_matchup(matchup, output_path="preview.png", max_pixels=256)

    :param matchup: matchup object whose products will be previewed.
    :param output_path: optional path at which to save the figure.
    :param collection_read_args: per-collection call-time overrides (same
        semantics as :py:meth:`BuildMUPreview.run`).
    :param max_pixels: maximum pixel extent in either spatial dimension after
        downsampling.
    :param context: optional :py:class:`~processor_tools.context.Context`
        supplying the ``preview.read`` config; defaults to the package default
        config.
    :return: matplotlib :py:class:`~matplotlib.figure.Figure`.
    """
    return BuildMUPreview(context=context).run(
        matchup=matchup,
        output_path=output_path,
        collection_read_args=collection_read_args,
        max_pixels=max_pixels,
    )


def build_geo_thumbnail(
    matchup: "Matchup",
    output_path: str,
    collection_read_args: Optional[dict] = None,
    max_pixels: int = _DEFAULT_MAX_PIXELS,
    context: Optional[EOMatchContext] = None,
) -> None:
    """Generate a georeferenced RGBA GeoTIFF overview thumbnail for a matchup.

    Convenience wrapper around :py:meth:`BuildMUPreview.build_geo_thumbnail`.
    Both tiles are composited onto a WGS84 grid; the alpha channel is
    transparent outside tile footprints so the base map shows through in
    STAC Browser.

    Example usage::

        from eomatch.preview import build_geo_thumbnail

        build_geo_thumbnail(matchup, "overview.tif", max_pixels=512)

    :param matchup: matchup whose products will be composited.
    :param output_path: filesystem path at which to save the GeoTIFF.
    :param collection_read_args: per-collection read overrides (same
        semantics as :py:meth:`BuildMUPreview.run`).
    :param max_pixels: maximum pixel count along the longer geographic axis.
    :param context: optional :py:class:`~eomatch.context.EOMatchContext`
        supplying the ``preview.read`` config.
    """
    BuildMUPreview(context=context).build_geo_thumbnail(
        matchup=matchup,
        output_path=output_path,
        collection_read_args=collection_read_args,
        max_pixels=max_pixels,
    )


def preview_event(
    event: "MatchupEvent",
    output_path: Optional[str] = None,
) -> matplotlib.figure.Figure:
    """Generate a matplotlib figure showing product footprints for a matchup event.

    Delegates to :py:meth:`~eomatch.domain.MatchupEvent.plot`, which renders
    all product footprints from every matchup in the event's matchup set,
    deduplicated by product ID and coloured by collection using ``TABLEAU_COLORS``.

    Example usage::

        from eomatch.preview import preview_event

        fig = preview_event(event)
        fig = preview_event(event, output_path="event_thumbnail.png")

    :param event: matchup event whose product footprints will be rendered.
    :param output_path: optional path at which to save the figure.  Any format
        accepted by :py:func:`matplotlib.figure.Figure.savefig` is supported.
    :return: matplotlib :py:class:`~matplotlib.figure.Figure`.
    """
    import cartopy.crs as ccrs

    if event.matchup_set is None or len(event.matchup_set) == 0:
        raise ValueError("MatchupEvent has no matchup_set to plot.")

    fig = plt.figure()
    ax = plt.axes(projection=ccrs.PlateCarree())
    event.plot(ax=ax)

    if output_path is not None:
        fig.savefig(output_path, bbox_inches="tight", dpi=150, facecolor="white")
        logger.info("Event preview saved to %s", output_path)

    return fig


def build_event_geo_thumbnail(
    event: "MatchupEvent",
    output_path: str,
    max_pixels: int = _DEFAULT_MAX_PIXELS,
) -> None:
    """Generate a georeferenced RGBA GeoTIFF thumbnail for a matchup event.

    Rasterizes the footprint polygons of all products in the event onto a
    WGS84 (EPSG:4326) grid, coloured by collection using matplotlib's
    ``TABLEAU_COLORS``.  The alpha channel is semi-transparent (180/255) over
    polygon areas and fully transparent elsewhere, so the image overlays
    correctly on STAC Browser's slippy map base layer.

    Products shared across multiple matchups are drawn only once.  Collections
    are assigned colours in the order they appear in ``event.collections``,
    matching the colour assignment in
    :py:meth:`~scrappi.ProductItemSet.plot_geometries`.

    Example usage::

        from eomatch.preview import build_event_geo_thumbnail

        build_event_geo_thumbnail(event, "event_overview.tif", max_pixels=512)

    :param event: matchup event whose product footprints will be rasterized.
    :param output_path: filesystem path at which to save the GeoTIFF.
    :param max_pixels: maximum pixel count along the longer geographic axis of
        the output raster.
    """
    import matplotlib.colors as mcolors
    import rasterio
    from rasterio.crs import CRS
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds

    if event.matchup_set is None or len(event.matchup_set) == 0:
        raise ValueError("MatchupEvent has no matchup_set to generate thumbnail from.")

    west = event.geometry["longitude_minimum"]
    south = event.geometry["latitude_minimum"]
    east = event.geometry["longitude_maximum"]
    north = event.geometry["latitude_maximum"]

    lon_span = east - west
    lat_span = north - south
    if lon_span >= lat_span:
        out_w = max_pixels
        out_h = max(1, round(max_pixels * lat_span / lon_span))
    else:
        out_h = max_pixels
        out_w = max(1, round(max_pixels * lon_span / lat_span))

    out_transform = from_bounds(west, south, east, north, out_w, out_h)
    wgs84 = CRS.from_epsg(4326)

    # Assign TABLEAU_COLORS to collections in order, matching plot_geometries
    tableau_keys = list(mcolors.TABLEAU_COLORS.keys())
    collection_colors: dict = {}
    for i, col in enumerate(event.collections):
        hex_color = mcolors.TABLEAU_COLORS[tableau_keys[i % len(tableau_keys)]]
        r, g, b = (int(c * 255) for c in mcolors.to_rgb(hex_color))
        collection_colors[col] = (r, g, b)

    # Collect deduplicated product geometries grouped by collection
    geoms_by_collection: dict = {col: [] for col in event.collections}
    seen_ids: set = set()
    for matchup in event.matchup_set:
        for product in matchup.products:
            if product.id not in seen_ids:
                seen_ids.add(product.id)
                col = product.collection
                if col in geoms_by_collection:
                    geoms_by_collection[col].append(product.geometry)

    canvas = np.zeros((4, out_h, out_w), dtype=np.uint8)

    for col, geoms in geoms_by_collection.items():
        if not geoms:
            continue
        r, g, b = collection_colors[col]
        mask = rasterize(
            [(geom, 1) for geom in geoms],
            out_shape=(out_h, out_w),
            transform=out_transform,
            fill=0,
            dtype=np.uint8,
        )
        hit = mask > 0
        canvas[0, hit] = r
        canvas[1, hit] = g
        canvas[2, hit] = b
        canvas[3, hit] = 180  # semi-transparent fill

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "width": out_w,
        "height": out_h,
        "count": 4,
        "crs": wgs84,
        "transform": out_transform,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(canvas)

    logger.info("Event geo thumbnail saved to %s", output_path)
