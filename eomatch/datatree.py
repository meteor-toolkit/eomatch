"""eomatch.datatree - utility for building match-up DataTree datasets"""

from __future__ import annotations

from datetime import datetime
import shapely
import xarray as xr
from xarray.core.types import T_Dataset
from typing import TYPE_CHECKING, Dict, Optional, Iterable
from scrappi.product import ProductItemSet
from eomatch.context import EOMatchContext
import os
from eoio import read

if TYPE_CHECKING:
    from eomatch.domain import Matchup

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = ["BuildMUDT"]

_FALLBACK_VARS_SEL: Dict[str, list] = {"meas": [], "aux": []}
_FALLBACK_READ_PARAMS = {
    "use_chunks": False,
    "metadata_level": True,
    "save_extracted": False,
}
_FALLBACK_PROCESSORS = {}


class BuildMUDT:
    """Utility class for building matchup DataTree datasets.

    Reads each product in a :py:class:`~eomatch.domain.Matchup` via ``eoio``
    and assembles the results into an :py:class:`xarray.DataTree` with one node
    per sensor, keyed by the STAC collection ID.

    Example usage::

        from eomatch.datatree import BuildMUDT

        builder = BuildMUDT()
        mudt = builder.run(matchup)
        # mudt["LANDSAT_C2L1"], mudt["S2_MSI_L1C"], …
    """

    def __init__(
        self,
        context: Optional[EOMatchContext] = None,
    ) -> None:
        """Initialise the builder.

        :param context: optional :py:class:`~eomatch.context.EOMatchContext`
            supplying ``read`` config; defaults to ``EOMatchContext()``.
        """
        if context is None:
            self.context = EOMatchContext()
        else:
            self.context = context

    def run(
        self,
        matchup: "Matchup",
        collection_read_args: Optional[dict] = None,
    ) -> xr.DataTree:
        """Build a matchup DataTree from a :py:class:`~eomatch.domain.Matchup`.

        Per-collection ``vars_sel``, ``read_params``, and ``processors`` defaults are
        read from the ``read`` section of the context config (see
        :py:meth:`_resolve_read_kwargs`). ``collection_read_args`` overrides those
        defaults at call time.

        :param matchup: matchup whose products to read.
        :param collection_read_args: per-collection call-time overrides keyed by STAC
            collection ID (see :py:meth:`_resolve_read_kwargs`).
        :return: DataTree with one node per sensor, named by collection ID.
        :raises ValueError: if ``matchup.products`` is ``None``.
        """
        if matchup.products is None:
            raise ValueError("No products set in Matchup object")

        product_ds = self.read_products(
            matchup.products,
            matchup.collocation_region,
            collection_read_args=collection_read_args,
        )
        return self.to_datatree(product_ds)

    def _resolve_read_kwargs(
        self,
        collection: str,
        collection_read_args: Optional[dict],
    ) -> tuple:
        """Resolve ``eoio.read`` kwargs for a single product by merging config defaults
        with call-time overrides.

        Merge order (lowest → highest priority):

        1. Hardcoded fallbacks (``_FALLBACK_*`` module constants).
        2. ``read.defaults`` from the context config.
        3. ``read.collections.<collection>`` from the context config.
        4. ``collection_read_args[collection]`` from the call-time argument.

        ``vars_sel`` and ``processors`` are replaced wholesale at each level;
        ``read_params`` is merged at the sub-key level so individual keys can be
        overridden without losing the rest.

        :param collection: STAC collection ID of the product being read (e.g.
            ``"LANDSAT_C2L1"``).
        :param collection_read_args: per-collection call-time overrides keyed by
            collection ID.  The entry for ``collection`` (if present) may contain
            ``vars_sel`` (full replacement), ``read_params`` (sub-key merge), and/or
            ``processors`` (full replacement).
        :return: resolved ``(vars_sel, read_params, processors)`` tuple.
        """
        read_cfg = (self.context.get("read") or {}) if self.context else {}
        global_defaults = read_cfg.get("defaults") or {}
        collection_cfg = (read_cfg.get("collections") or {}).get(collection) or {}
        call_cfg = (collection_read_args or {}).get(collection) or {}

        # Build base: global defaults → config collection (sub-key merge for all)
        vars_sel = {
            **_FALLBACK_VARS_SEL,
            **global_defaults.get("vars_sel", {}),
            **collection_cfg.get("vars_sel", {}),
        }
        read_params = {
            **_FALLBACK_READ_PARAMS,
            **global_defaults.get("read_params", {}),
            **collection_cfg.get("read_params", {}),
        }
        processors = {
            **_FALLBACK_PROCESSORS,
            **global_defaults.get("processors", {}),
            **collection_cfg.get("processors", {}),
        }

        # Apply call-time per-collection overrides
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
    ) -> list:
        """Read each product in *product_item_set*, subsetting to *roi*.

        Products are read via ``eoio.read``.  If a product has not yet been
        downloaded and ``download=True``, it is fetched via scrappi before
        reading.  Each returned dataset carries a ``"collection"`` attribute
        set to the product's STAC collection ID, which is used by
        :py:meth:`to_datatree` to name the DataTree node.

        :param product_item_set: the set of products to read.
        :param roi: WGS-84 polygon defining the spatial region of interest
            passed to ``eoio`` as a subset.
        :param download: if ``True``, download missing products before reading.
        :param collection_read_args: per-collection call-time overrides (see
            :py:meth:`_resolve_read_kwargs`).
        :return: list of :py:class:`xarray.Dataset` objects, one per product.
        """

        product_ds = []
        for i, product in enumerate(product_item_set):
            # Prefer an absolute local path registered as a STAC "data" asset
            # (set by Matchup.from_stac_item when loading a downloaded catalogue
            # product) over scrappi's filesystem-derived path.
            # The asset href stores the bare product path (no extension); eoio
            # requires the path passed to it to exist, so supply the .tar.gz
            # variant when the bare directory has not yet been extracted.
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

            _vars_sel, _read_params, _processors = self._resolve_read_kwargs(
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

    def to_datatree(self, product_ds: Iterable[T_Dataset], opt_attrs: Optional[dict] = None) -> xr.DataTree:
        """Assemble an :py:class:`xarray.DataTree` from a list of per-sensor datasets.

        Each dataset becomes a child node named by its ``"collection"`` attribute
        (e.g. ``"LANDSAT_C2L1"``).  If the same collection appears more than once
        a numeric suffix is appended (``"LANDSAT_C2L1_2"``, etc.).

        :param product_ds: iterable of per-sensor datasets, each carrying a
            ``"collection"`` attribute identifying the STAC collection.
        :param opt_attrs: additional attributes to merge into the DataTree root.
        :return: DataTree with one child node per sensor and a ``date_created``
            root attribute.
        :raises ValueError: if ``product_ds`` is ``None``.
        """
        if product_ds is None:
            raise ValueError("No products set in Matchup object.")

        mudt = xr.DataTree()

        seen: dict[str, int] = {}
        for product in product_ds:
            base = product.attrs.get("collection") or "sensor"
            count = seen.get(base, 0)
            seen[base] = count + 1
            node_name = base if count == 0 else f"{base}_{count + 1}"
            mudt[node_name] = product

        mudt.attrs.update({"date_created": datetime.now().strftime("%d/%m/%Y %H:%M:%S")})
        return mudt


if __name__ == "__main__":
    pass
