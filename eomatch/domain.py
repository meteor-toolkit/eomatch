"""eomatch.domain - domain model for matchup events and matchups"""

import numpy as np
import pystac
from scrappi import ProductItemSet
from scrappi.product import product_item_from_stac
from scrappi.utils.plot_utils import prepare_map_plot
import cartopy.crs as ccrs
from shapely.geometry import Polygon, mapping
import datetime as dt
from typing import Dict, Union, Tuple, List, Optional
import xarray as xr
from matplotlib import pyplot as plt

from eomatch.datatree import BuildMUDT
from eomatch.context import EOMatchContext
from scrappi.utils.utils import convert_datetime

__author__ = [
    "Sam Hunt <sam.hunt@npl.co.uk>",
    "Maddie Stedman <maddie.stedman@npl.co.uk>",
]
__all__ = [
    "MatchupSet",
    "Matchup",
    "MatchupEvent",
    "MatchupEventSet",
    "MATCHUP_EVENTS_COLLECTION_PREFIX",
]

MATCHUP_EVENTS_COLLECTION_PREFIX = "matchup-events"


def _matchup_collection_id(collections: List[str], platforms: List[str]) -> str:
    """Return a stable collection-pair ID that includes platform names.

    Pairs are sorted by collection name so the result is the same regardless of
    the order the arguments are supplied.

    :param collections: STAC collection IDs for each sensor.
    :param platforms: platform names aligned with ``collections``.
    :return: e.g. ``"LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A"``
    """
    pairs = sorted(zip(collections, platforms), key=lambda x: x[0])
    return "-vs-".join(f"{col}-{plat}" for col, plat in pairs)


def _matchup_events_collection_id(collections: List[str], platforms: List[str]) -> str:
    """Return a stable events-collection ID that includes platform names.

    :param collections: STAC collection IDs for each sensor.
    :param platforms: platform names aligned with ``collections``.
    :return: e.g. ``"matchup-events-LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A"``
    """
    return f"{MATCHUP_EVENTS_COLLECTION_PREFIX}-{_matchup_collection_id(collections, platforms)}"


class Matchup:
    """
    Interface collocated products

    :param products: list of product info dictionaries (from :py:func:`scrappi.return`
    """

    def __init__(
        self,
        products: Optional[ProductItemSet] = None,
        context: Optional[EOMatchContext] = None,
        assets: Optional[Dict[str, pystac.Asset]] = None,
    ) -> None:
        # Initial product info attributes
        self._products: Optional[ProductItemSet] = None

        if products is not None:
            self.products = products

        self.context = context if context is not None else EOMatchContext()

        self.assets: Dict[str, pystac.Asset] = assets if assets is not None else {}

    def __str__(self):
        """Custom __str__"""
        repr_str = "<eomatch.Matchup (bounds: {}, start_time: {})>\nProducts:".format(
            self.collocation_region.bounds, self.product_time_bounds[0]
        )

        for p in self.products:
            repr_str += "\n\t{}: \t{}".format(p.collection, p.id)

        return repr_str

    def __repr__(self):
        """Custom  __repr__"""
        return str(self)

    @property
    def products(self):
        return self._products

    @products.setter
    def products(self, products):
        # sort products by collection in alphabetical order
        products.sort(sort_by="collection")
        self._products = products

        # check products overlap
        if self.collocation_region.is_empty:
            raise ValueError("Product geometries do not intersect")

    @property
    def collocation_region(self) -> Union[None, Polygon]:
        """
        Returns polygon of collocation region for matchup products

        :return: collocation region shape
        """
        if self.products is not None:
            col_reg = self.products[0].geometry
            for prod in self.products[1:]:
                col_reg = col_reg.intersection(prod.geometry)

            return col_reg

        else:
            return None

    @property
    def product_time_bounds(self) -> Union[None, Tuple[dt.datetime, dt.datetime]]:
        """
        Returns earliest start time and latest stop time of matchup products

        :return: matchup product time bounds
        """

        if self.products is not None:
            return (
                min([p.start_time for p in self.products]),
                max([p.stop_time for p in self.products]),
            )
        else:
            return None

    @property
    def time_diff_abs(self) -> Union[None, float]:
        """
        Returns the absolute time difference between matchup product start times in seconds

        :return: product time difference in seconds
        """

        if self.products is not None:
            min_start_time = min([p.start_time for p in self.products])
            max_start_time = max([p.start_time for p in self.products])
            td = max_start_time - min_start_time
            return td.total_seconds()

        else:
            return None

    def time_diff(self, collection1: Optional[str] = None, collection2: Optional[str] = None) -> Optional[float]:
        """
        Returns the time difference ``collection2 - collection1`` in total seconds.

        If both arguments are ``None``, returns ``products[1].start_time - products[0].start_time``
        (useful for pairwise matchups where collection order does not matter).
        If either collection name is provided but not found, returns ``None``.

        :param collection1: Collection name of the first product.
        :param collection2: Collection name of the second product.
        :return: Time difference in seconds, or ``None`` if products are not set or a named
            collection is not found.
        """
        if self.products is None:
            return None

        if collection1 is None and collection2 is None:
            td = self.products[1].start_time - self.products[0].start_time
            return td.total_seconds()

        product1 = next((p for p in self.products if p.collection == collection1), None)
        product2 = next((p for p in self.products if p.collection == collection2), None)

        if product1 is None or product2 is None:
            return None

        return (product2.start_time - product1.start_time).total_seconds()

    def return_matchup_dataset(
        self,
        collection_read_args: Optional[dict] = None,
    ) -> xr.DataTree:
        """
        Return match-up dataset by downloading the products if required, reading in data
        for each product and assembling a match-up DataTree.

        Per-collection ``vars_sel``, ``read_params``, and ``processors`` defaults are
        read from the ``read`` section of the context config (see
        :py:meth:`~eomatch.datatree.BuildMUDT._resolve_read_kwargs` for the full
        merge order). ``collection_read_args`` overrides those defaults at call time.

        **Basic usage** — rely entirely on config defaults::

            dt = matchup.return_matchup_dataset()

        **Select specific bands per collection** — each collection has its own variable
        names, so override per collection keyed by STAC collection ID.
        ``vars_sel`` within a collection is a full replacement::

            dt = matchup.return_matchup_dataset(
                collection_read_args={
                    "S2_MSI_L1C":   {"vars_sel": {"meas": ["B02", "B03", "B04", "B08"]}},
                    "LANDSAT_C2L1": {"vars_sel": {"meas": ["B2",  "B3",  "B4",  "B5" ]}},
                }
            )

        **Apply specific processors per collection**::

            dt = matchup.return_matchup_dataset(
                collection_read_args={
                    "S2_MSI_L1C": {"processors": {"toa_reflectance": {}}},
                }
            )

        **Nudge a read parameter for one collection** — ``read_params`` within a
        collection entry is merged at the sub-key level::

            dt = matchup.return_matchup_dataset(
                collection_read_args={
                    "LANDSAT_C2L1": {"read_params": {"use_chunks": True}},
                }
            )

        :param collection_read_args: per-collection call-time overrides, keyed by
            STAC collection ID.  Each value is a dict with any of the keys
            ``vars_sel`` (full replacement), ``read_params`` (sub-key merge), and
            ``processors`` (full replacement).  Takes precedence over config defaults
            for that collection.
        :return: match-up DataTree with one node per sensor (``sensor_1``, ``sensor_2``, …)
        :raises ValueError: if no products are set on this matchup
        """
        if self.products is None:
            raise ValueError("No products set in Matchup object.")
        mu_ds = BuildMUDT(context=self.context).run(
            self,
            collection_read_args=collection_read_args,
        )
        return mu_ds

    @property
    def stac_id(self) -> Optional[str]:
        """STAC Item ID for this matchup, or ``None`` if no products are set.

        Built from the collection ID, the acquisition datetime of each product
        in sorted-collection order, and the collocation region's bounding box.
        Using per-product datetimes (rather than the single matchup
        start_time) avoids collisions when one sensor records time at day
        precision only — e.g. Landsat stores all acquisitions as midnight
        UTC, so using only its timestamp collapses every same-day matchup to
        one ID.  The bounding box is appended for the same reason: two
        same-day acquisitions from a day-precision sensor can still share an
        identical timestamp while occurring at different locations.
        """
        if self.products is None:
            return None
        collection_id = _matchup_collection_id(
            [p.collection for p in self.products],
            [p.platform for p in self.products],
        )
        times = "_".join(p.start_time.strftime("%Y%m%dT%H%M%S") for p in self.products)
        collocation_region = self.collocation_region
        assert collocation_region is not None
        lon_min, lat_min, lon_max, lat_max = collocation_region.bounds
        return f"{collection_id}_{times}_{lon_min:.2f}_{lat_min:.2f}_{lon_max:.2f}_{lat_max:.2f}"

    def to_stac_item(self, event_id: Optional[str] = None) -> pystac.Item:
        """
        Return a STAC Item representing this matchup.

        :param event_id: ID of the parent MatchupEvent STAC Item, if known.
        :return: STAC Item for this matchup.
        :raises ValueError: if no products are set.
        """
        if self.products is None:
            raise ValueError("Cannot serialise Matchup to STAC: no products set.")
        collocation_region = self.collocation_region
        assert collocation_region is not None
        time_bounds = self.product_time_bounds
        assert time_bounds is not None
        start_time, stop_time = time_bounds
        stac_id = self.stac_id
        assert stac_id is not None
        collections = [p.collection for p in self.products]
        platforms = [p.platform for p in self.products]
        collection_id = _matchup_collection_id(collections, platforms)

        properties = {
            "end_datetime": stop_time.isoformat(),
            "matchup:collections": collections,
            "matchup:platforms": platforms,
            "matchup:time_diff_abs": self.time_diff_abs,
        }
        if event_id is not None:
            properties["matchup:event_id"] = event_id

        item = pystac.Item(
            id=stac_id,
            geometry=mapping(collocation_region),
            bbox=list(collocation_region.bounds),
            datetime=start_time,
            properties=properties,
            collection=collection_id,
        )

        for product in self.products:
            product_item = product.to_stac_item()
            if product_item.collection_id is None:
                product_item.collection_id = product.collection or None
            item.add_link(
                pystac.Link(
                    rel="derived_from",
                    target=product_item,
                    media_type=pystac.MediaType.JSON,
                )
            )

        return item

    @classmethod
    def from_stac_item(cls, item: pystac.Item) -> "Matchup":
        """
        Reconstruct a Matchup from a STAC Item.

        Source ProductItems are rebuilt from the ``derived_from`` link targets.
        They carry geometry and timing information but no filesystem / API
        configuration — call ``product.set_api()`` and ``product.set_fs()``
        before attempting a download.

        :param item: STAC Item produced by :py:meth:`to_stac_item`.
        :return: Matchup object.
        """
        derived = [lnk for lnk in item.links if lnk.rel == "derived_from"]
        products = []
        for link in derived:
            target = link.target
            if not isinstance(target, pystac.Item):
                href = link.get_absolute_href()
                if href is None:
                    raise ValueError(
                        f"Cannot resolve derived_from link for item {item.id!r}: "
                        "link has no absolute href and the owning item has no self_href."
                    )
                target = pystac.Item.from_file(href)
            product = product_item_from_stac(target)
            if not product.collection:
                product.collection = target.collection_id or ""
            # Resolve the "data" asset href to an absolute local path so that
            # BuildMUDT can locate the downloaded product without going through
            # scrappi's filesystem configuration.
            if "data" in target.assets:
                abs_href = target.assets["data"].get_absolute_href()
                if abs_href:
                    product.url = abs_href
            products.append(product)

        return cls(ProductItemSet(products), assets=dict(item.assets))

    def plot_geometries(self, ax=None):
        """
        plot geometries in matchup set
        """
        self.products.plot_geometries(ax)


class MatchupSet:
    """
    Container for :py:class:`~eomatch.Matchup` objects
    """

    def __init__(self, matchups: Optional[List[Matchup]] = None) -> None:
        # Initial product info attributes
        self._matchups: List[Matchup] = matchups if matchups is not None else []
        self._collections: Union[None, List[Tuple[str, ...]]] = None

    def __str__(self):
        """Custom __str__"""
        repr_str = "<eomatch.MatchupSet>\nMatchup Products:"
        indices: List = list(range(len(self))) if len(self) < 10 else [0, 1, 2, None, -3, -2, -1]
        for idx in indices:
            if idx is None:
                repr_str += "\n\t..."
            else:
                mu = self[idx]
                products_str = ", ".join(p.collection for p in mu.products)
                repr_str += f"\n\t[{products_str}]"
        return repr_str

    def __repr__(self):
        """Custom  __repr__"""
        return str(self)

    def __getitem__(self, idx) -> Matchup:
        return self._matchups[idx]

    def __len__(self) -> int:
        return len(self._matchups)

    def __iter__(self):
        return iter(self._matchups)

    def append(self, matchup: Matchup):
        """Append a Matchup to the set."""
        self._matchups.append(matchup)
        self._collections = None  # invalidate cache

    def plot_geometries(self, ax):
        """
        plot geometries in matchup set
        """
        for matchup in self._matchups:
            matchup.plot_geometries(ax)

    def plot_points(self, ax=None, tick_step: Optional[float] = None, mi=0, mui=0):

        if ax is None:
            plt.figure()
            ax = plt.axes(projection=ccrs.PlateCarree())

        # Add map styling
        prepare_map_plot(ax, tick_step=tick_step)

        # Draw geometry
        colors = plt.get_cmap("coolwarm")(np.linspace(0, 1, len(self) + mi))
        for m, mu in enumerate(self):
            m += mui
            if m % 2 == 0:
                mu_coords = mu.collocation_region.centroid.coords[0]
                plt.plot(
                    mu_coords[0],
                    mu_coords[1],
                    ".",
                    alpha=0.8,
                    markersize=5,
                    color=colors[m],
                )

        plt.tight_layout()

    @property
    def collections(self) -> List[Tuple[str, ...]]:
        """
        Returns collection sets of matchups within matchup set

        :return: matchup collections
        """

        if self._collections is not None:
            pass

        else:
            collections = set()
            for mu in self._matchups:
                cols = tuple(mu.products.collections)
                collections.add(cols)

            self._collections = list(collections)

        return self._collections


class MatchupEvent:
    """
    Interface event of satellites crossing each other

    :param products: list of product info dictionaries (from :py:func:`scrappi.return`
    """

    def __init__(
        self,
        collections: List[str],
        platforms: List[str],
        start_time: dt.datetime,
        stop_time: dt.datetime,
        latitude_minimum: float,
        longitude_minimum: float,
        latitude_maximum: float,
        longitude_maximum: float,
        context: Optional[EOMatchContext] = None,
        assets: Optional[Dict[str, pystac.Asset]] = None,
    ) -> None:
        self.collections = collections
        self.platforms = platforms
        self.start_time = convert_datetime(start_time)
        self.stop_time = convert_datetime(stop_time)
        self.geometry = {
            "latitude_minimum": latitude_minimum,
            "longitude_minimum": longitude_minimum,
            "latitude_maximum": latitude_maximum,
            "longitude_maximum": longitude_maximum,
        }

        self.context = context if context is not None else EOMatchContext()

        self.assets: Dict[str, pystac.Asset] = assets if assets is not None else {}
        self._matchup_set: Optional[MatchupSet] = None

    @property
    def matchup_set(self) -> Optional["MatchupSet"]:
        return self._matchup_set

    @matchup_set.setter
    def matchup_set(self, matchup_set: "MatchupSet") -> None:
        if not isinstance(matchup_set, MatchupSet):
            raise TypeError(f"Expected MatchupSet, got {type(matchup_set).__name__}")
        expected = tuple(sorted(self.collections))
        for cols in matchup_set.collections:
            if tuple(sorted(cols)) != expected:
                raise ValueError(
                    f"MatchupSet collections {cols} inconsistent with event collections {self.collections}"
                )
        self._matchup_set = matchup_set

    def __str__(self):
        """Custom __str__"""
        repr_str = "<eomatch.MatchupEvent ({}, times: {}, bounds: {})".format(
            self.platformstring, [self.start_time, self.stop_time], self.geometry
        )

        return repr_str

    def __repr__(self):
        """Custom  __repr__"""
        return str(self)

    def to_stac_item(self) -> pystac.Item:
        """
        Return a STAC Item representing this matchup event.

        :return: STAC Item for this event.
        """
        lon_min = self.geometry["longitude_minimum"]
        lat_min = self.geometry["latitude_minimum"]
        lon_max = self.geometry["longitude_maximum"]
        lat_max = self.geometry["latitude_maximum"]

        return pystac.Item(
            id=self.stac_id,
            geometry={
                "type": "Polygon",
                "coordinates": [
                    [
                        [lon_min, lat_min],
                        [lon_max, lat_min],
                        [lon_max, lat_max],
                        [lon_min, lat_max],
                        [lon_min, lat_min],
                    ]
                ],
            },
            bbox=[lon_min, lat_min, lon_max, lat_max],
            datetime=self.start_time,
            properties={
                "end_datetime": self.stop_time.isoformat(),
                "matchup:platforms": self.platforms,
                "matchup:collections": self.collections,
            },
            collection=_matchup_events_collection_id(self.collections, self.platforms),
        )

    @classmethod
    def from_stac_item(cls, item: pystac.Item) -> "MatchupEvent":
        """
        Reconstruct a MatchupEvent from a STAC Item.

        :param item: STAC Item produced by :py:meth:`to_stac_item`.
        :return: MatchupEvent object.
        """
        assert item.bbox is not None
        lon_min, lat_min, lon_max, lat_max = item.bbox
        assert item.datetime is not None
        props = item.properties

        return cls(
            platforms=props["matchup:platforms"],
            collections=props["matchup:collections"],
            start_time=item.datetime,
            stop_time=dt.datetime.fromisoformat(props["end_datetime"]),
            latitude_minimum=lat_min,
            longitude_minimum=lon_min,
            latitude_maximum=lat_max,
            longitude_maximum=lon_max,
            assets=dict(item.assets),
        )

    def get_scrappi_queries(self) -> List[dict]:
        """
        Prepare one scrappi query per collection/platform pair in this MatchupEvent.

        Each query targets a single collection and includes the corresponding platform
        name so callers can route results without inspecting the returned products.

        :return: list of scrappi query dicts, one per collection/platform pair.
        """
        queries = []
        for collection, platform in zip(self.collections, self.platforms):
            queries.append(
                {
                    "collections": collection,
                    "geom": self.geometry,
                    "start_time": self.start_time.isoformat(),
                    "stop_time": self.stop_time.isoformat(),
                    "platform": platform,
                }
            )
        return queries

    def plot(
        self,
        ax=None,
        show_bbox: bool = False,
        tick_step: Optional[float] = None,
    ):
        """
        Plot the product footprints for all matchups in this event's matchup_set,
        coloured by collection. Products shared across multiple matchups are drawn
        only once. Optionally overlays the event bounding box as a dashed rectangle.

        :param ax: existing cartopy ``PlateCarree`` axes to draw onto; a new figure
            is created when not provided.
        :param show_bbox: if ``True``, draw the event lat/lon bounding box as a
            dashed rectangle.
        :param tick_step: lat/lon axis tick separation passed through to
            :py:meth:`~scrappi.ProductItemSet.plot_geometries`.
        :return: the axes object.

        Example usage::

            event = events[0]
            event.plot(show_bbox=True)
            plt.show()
        """
        if self._matchup_set is None or len(self._matchup_set) == 0:
            raise ValueError("MatchupEvent has no matchup_set to plot.")

        if ax is None:
            plt.figure()
            ax = plt.axes(projection=ccrs.PlateCarree())

        # Deduplicate products across matchups so each footprint is drawn once
        all_products = ProductItemSet()
        seen_ids: set = set()
        for matchup in self._matchup_set:
            for product in matchup.products:
                if product.id not in seen_ids:
                    all_products.add_ProductItem(product)
                    seen_ids.add(product.id)

        all_products.plot_geometries(ax=ax, tick_step=tick_step)

        if show_bbox:
            lon_min = self.geometry["longitude_minimum"]
            lat_min = self.geometry["latitude_minimum"]
            lon_max = self.geometry["longitude_maximum"]
            lat_max = self.geometry["latitude_maximum"]
            ax.plot(
                [lon_min, lon_max, lon_max, lon_min, lon_min],
                [lat_min, lat_min, lat_max, lat_max, lat_min],
                color="black",
                linestyle="--",
                linewidth=1.5,
                transform=ccrs.PlateCarree(),
            )

        return ax

    @property
    def platformstring(self) -> str:
        """Return platform names joined by underscore."""
        return "_".join(self.platforms)

    @property
    def stac_id(self) -> str:
        """STAC Item ID for this matchup event.

        Includes the collection pair so events for different collection-pairs
        sharing the same platforms and start-time second do not collide.
        """
        return f"{_matchup_collection_id(self.collections, self.platforms)}_{self.start_time.strftime('%Y%m%dT%H%M%S')}"


class MatchupEventSet:
    """
    Container for :py:class:`~eomatch.MatchupEvent` objects
    """

    def __init__(self, events: Optional[List["MatchupEvent"]] = None) -> None:
        self._events: List["MatchupEvent"] = events if events is not None else []

    def __str__(self):
        repr_str = "<eomatch.MatchupEventSet>\nEvents:"

        if len(self) < 10:
            for event in self:
                repr_str += f"\n\t{event}"
        else:
            for idx in [0, 1, 2, -3, -2, -1]:
                if idx == -3:
                    repr_str += "\n..."
                else:
                    repr_str += f"\n\t{self[idx]}"

        return repr_str

    def __repr__(self):
        return str(self)

    def __getitem__(self, idx) -> "MatchupEvent":
        return self._events[idx]

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):
        return iter(self._events)

    def append(self, event: "MatchupEvent") -> None:
        self._events.append(event)


if __name__ == "__main__":
    pass
