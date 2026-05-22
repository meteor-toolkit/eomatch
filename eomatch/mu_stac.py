"""eomatch.mu_stac - STAC catalogue for matchup events and matchups"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import shutil
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, cast
from eomatch.context import EOMatchContext
import pystac
from scrappi import ProductItem
from scrappi.fs.stacfilesystem import STACFileSystem

from eomatch.domain import (
    Matchup,
    MatchupEvent,
    MatchupEventSet,
    MatchupSet,
    MATCHUP_EVENTS_COLLECTION_PREFIX,
    _matchup_collection_id,
    _matchup_events_collection_id,
)

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = ["MatchupCatalogue"]


def _fix_stac_hrefs(root_dir: str) -> None:
    """Replace ``stac://`` root-link hrefs with proper relative paths.

    Some pystac versions write ``stac://catalog.json`` as the ``root`` link
    href in saved JSON files rather than a proper relative path.  That scheme
    is pystac-internal and cannot be resolved by urllib3, so any catalogue
    saved by an affected version raises ``URLSchemeUnknown: Not supported URL
    scheme stac`` as soon as pystac tries to traverse children.

    This function walks every ``*.json`` file under *root_dir* and rewrites
    ``stac://`` hrefs in ``root`` links to the correct relative path, fixing
    both existing catalogues (called from :py:meth:`MatchupCatalogue.open`)
    and freshly saved ones (called from :py:meth:`MatchupCatalogue.save`).

    :param root_dir: catalogue root directory containing ``catalog.json``.
    """
    catalog_path = os.path.join(root_dir, "catalog.json")
    for json_path in glob.glob(os.path.join(root_dir, "**", "*.json"), recursive=True):
        try:
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        changed = False
        for link in data.get("links", []):
            if link.get("href", "").startswith("stac://"):
                rel_root = os.path.relpath(catalog_path, os.path.dirname(json_path))
                link["href"] = rel_root.replace(os.sep, "/")
                changed = True
        if changed:
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)


def _properties_match(item: pystac.Item, properties: Dict[str, Any]) -> bool:
    """Return ``True`` if *item* satisfies every condition in *properties*.

    Each entry in *properties* maps a property key to either:

    - A bare value — checked for equality.
    - A ``dict`` of operator → threshold pairs.  Supported operators are
      ``lt``, ``lte``, ``gt``, ``gte``, ``eq``, ``ne``, and ``in`` (list
      membership).  All operators in a single entry must pass.

    Items that lack a required key are treated as non-matching.

    :param item: STAC Item whose ``properties`` dict is inspected.
    :param properties: filter specification, e.g.
        ``{"time_diff_s": {"lt": 900}, "land_fraction": {"lt": 0.2}}``.
    :return: ``True`` if all conditions are satisfied.
    """
    _OPS = {
        "lt": lambda v, t: v < t,
        "lte": lambda v, t: v <= t,
        "gt": lambda v, t: v > t,
        "gte": lambda v, t: v >= t,
        "eq": lambda v, t: v == t,
        "ne": lambda v, t: v != t,
        "in": lambda v, t: v in t,
    }
    for key, condition in properties.items():
        value = item.properties.get(key)
        if value is None:
            return False
        if isinstance(condition, dict):
            for op, threshold in condition.items():
                fn = _OPS.get(op)
                if fn is None:
                    raise ValueError(f"Unknown filter operator {op!r}. Supported: {list(_OPS)}")
                if not fn(value, threshold):
                    return False
        else:
            if value != condition:
                return False
    return True


class MatchupCatalogue:
    """STAC catalogue organising matchup events and matchup items.

    Structure::

        catalogue/
        ├── catalog.json
        ├── {collection-1}/
        │   ├── collection.json
        │   └── YYYY/MM/DD/{item-id}.json     # one per source product
        ├── {collection-2}/
        │   └── …
        ├── matchup-events-{col-1}-{plat-1}-vs-{col-2}-{plat-2}/
        │   ├── collection.json
        │   └── YYYY/MM/DD/{item-id}.json     # one per MatchupEvent
        └── {col-1}-{plat-1}-vs-{col-2}-{plat-2}/
            ├── collection.json
            └── YYYY/MM/DD/{item-id}.json     # one per Matchup

    Each matchup Item links to its source products via ``derived_from`` and
    references its parent event via a ``matchup:event_id`` property and a
    ``related`` link.
    """

    def __init__(
        self,
        id: Optional[str] = None,
        description: Optional[str] = None,
        path: Optional[str] = None,
        catalog: Optional[pystac.Catalog] = None,
        context: Optional[EOMatchContext] = None,
    ) -> None:
        if context is None:
            context = EOMatchContext()
        self.context = context

        cfg: dict = context.get("matchup_catalogue") or {}

        _path = path if path is not None else cfg.get("path")
        _id = id if id is not None else (cfg.get("id") or "matchup-catalogue")
        _description = description if description is not None else (cfg.get("description") or "Matchup catalogue")

        self.path = _path
        self.product_fs: Optional[STACFileSystem] = STACFileSystem(path=_path) if _path is not None else None

        if catalog is not None:
            self.catalog = catalog
        else:
            if path is not None:
                catalog_json = os.path.join(path, "catalog.json")
                if os.path.exists(catalog_json):
                    raise FileExistsError(
                        f"A catalogue already exists at {catalog_json!r}. Use MatchupCatalogue.open() to load it."
                    )
            self.catalog = pystac.Catalog(id=_id, description=_description)

    def _get_or_create_collection(self, collection_id: str, description: str) -> pystac.Collection:
        existing = self.catalog.get_child(collection_id)
        if existing is not None:
            return cast(pystac.Collection, existing)
        _none_interval: List[List[Optional[dt.datetime]]] = [[None, None]]
        col = pystac.Collection(
            id=collection_id,
            description=description,
            extent=pystac.Extent(
                spatial=pystac.SpatialExtent(bboxes=[[-180.0, -90.0, 180.0, 90.0]]),
                temporal=pystac.TemporalExtent(intervals=_none_interval),
            ),
        )
        self.catalog.add_child(col)
        return col

    def add_event(self, event: "MatchupEvent") -> pystac.Item:
        """Add a MatchupEvent to the catalogue, returning its STAC Item.

        If the event has a registered ``matchup_set``, its matchups are also
        added to the catalogue. The event Item carries a ``related`` link
        (``matchup:role=matchup``) for each matchup Item, so that
        :py:meth:`get_events` can navigate forward from event to matchups
        without scanning the whole matchup collection.

        If an Item with the same ID already exists in the catalogue the
        existing Item is returned unchanged (idempotent).
        """
        item = event.to_stac_item()
        assert item.collection_id is not None
        events_col = self._get_or_create_collection(
            item.collection_id,
            f"Matchup events: {item.collection_id}",
        )
        existing = next(events_col.get_items(item.id), None)
        if existing is not None:
            return existing
        events_col.add_item(item)
        if event.matchup_set is not None:
            linked_mu_ids: set = set()
            for mu in event.matchup_set:
                mu_item = self.add_matchup(mu, event_id=item.id)
                if mu_item.id not in linked_mu_ids:
                    item.add_link(
                        pystac.Link(
                            rel="related",
                            target=mu_item,
                            media_type=pystac.MediaType.JSON,
                            extra_fields={"matchup:role": "matchup"},
                        )
                    )
                    mu_item.add_link(
                        pystac.Link(
                            rel="related",
                            target=item,
                            media_type=pystac.MediaType.JSON,
                            extra_fields={"matchup:role": "event"},
                        )
                    )
                    linked_mu_ids.add(mu_item.id)
        return item

    def add_matchup(self, matchup: "Matchup", event_id: Optional[str] = None) -> pystac.Item:
        """Add a Matchup and its source products to the catalogue, returning its STAC Item.

        If an Item with the same ID already exists in the catalogue the
        existing Item is returned unchanged (idempotent).
        """
        item = matchup.to_stac_item(event_id=event_id)
        assert item.collection_id is not None
        matchup_col = self._get_or_create_collection(item.collection_id, f"Matchups: {item.collection_id}")
        existing = next(matchup_col.get_items(item.id), None)
        if existing is not None:
            return existing
        for link in [lnk for lnk in item.links if lnk.rel == "derived_from"]:
            product_item = cast(pystac.Item, link.target)
            assert product_item.collection_id is not None
            col = self._get_or_create_collection(product_item.collection_id, f"Products: {product_item.collection_id}")
            existing_product = next(col.get_items(product_item.id), None)
            if existing_product is None:
                col.add_item(product_item)
            else:
                link.target = existing_product
        matchup_col.add_item(item)
        return item

    def get_events(
        self,
        collections: Optional[List[str]] = None,
        platforms: Optional[List[str]] = None,
        start_time: Optional[dt.datetime] = None,
        stop_time: Optional[dt.datetime] = None,
        bbox: Optional[List[float]] = None,
        products_downloaded: bool = False,
        properties: Optional[Dict[str, Any]] = None,
    ) -> MatchupEventSet:
        """Return MatchupEvents from the catalogue, each with its MatchupSet populated.

        Filtering is applied directly against the STAC Item properties before any
        Python objects are reconstructed, so events that do not match are skipped cheaply.

        The *properties* filter operates on matchup items (not event items).  Each
        key maps to a bare value (equality) or a dict of operator → threshold pairs.
        Supported operators: ``lt``, ``lte``, ``gt``, ``gte``, ``eq``, ``ne``, ``in``.
        Matchups that do not satisfy all conditions are excluded; events with no remaining
        matchups are dropped entirely.  Properties must have been added to the items first
        via :py:func:`eomatch.enrich.enrich`.

        Example::

            events = cat.get_events(
                properties={
                    "time_diff_s": {"lt": 900},
                    "land_fraction": {"lt": 0.2},
                }
            )

        :param collections: restrict to one sensor pair, e.g. ``["LANDSAT_C2L1", "S3_EFR"]``.
        :param platforms: return only events that include at least one of these platforms.
        :param start_time: return only events whose stop time is at or after this datetime.
        :param stop_time: return only events whose start time is at or before this datetime.
        :param bbox: spatial overlap filter as ``[lon_min, lat_min, lon_max, lat_max]``.
        :param products_downloaded: if ``True``, only include matchups whose every source
            product has been downloaded (``scrappi:asset_state: downloaded`` on its ``data``
            asset). Events with no qualifying matchups are omitted entirely.
        :param properties: property filter applied to each matchup STAC Item.  Only
            matchups whose items satisfy all conditions are included.
        :return: :py:class:`MatchupEventSet` with ``matchup_set`` populated where matchups exist.
        """
        # collection IDs now include platform, e.g. "LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A".
        # Filter by checking that every requested collection name appears in the ID.
        filter_collections = sorted(collections) if collections is not None else None
        prefix = f"{MATCHUP_EVENTS_COLLECTION_PREFIX}-"

        item_cache: dict = {}  # href -> pystac.Item, shared across all events

        events = MatchupEventSet()
        for events_col in self.catalog.get_children():
            if not events_col.id.startswith(prefix):
                continue
            if filter_collections is not None and not all(
                col in events_col.id[len(prefix) :] for col in filter_collections
            ):
                continue

            for event_item in events_col.get_items():
                if not self._event_item_matches(event_item, platforms, start_time, stop_time, bbox):
                    continue

                event = MatchupEvent.from_stac_item(event_item)

                mu_links = [
                    lnk
                    for lnk in event_item.links
                    if lnk.rel == "related" and lnk.extra_fields.get("matchup:role") == "matchup"
                ]
                matchups = []
                for lnk in mu_links:
                    if isinstance(lnk.target, pystac.Item):
                        mu_item = lnk.target
                    else:
                        href = lnk.get_absolute_href()
                        if href is None:
                            continue
                        if href not in item_cache:
                            item_cache[href] = pystac.Item.from_file(href)
                        mu_item = item_cache[href]

                    # Pre-resolve derived_from links using the cache so that
                    # Matchup.from_stac_item does not re-read the same product
                    # files for every matchup that shares a product.
                    for derived_link in mu_item.links:
                        if derived_link.rel == "derived_from" and not isinstance(derived_link.target, pystac.Item):
                            prod_href = derived_link.get_absolute_href()
                            if prod_href is None:
                                continue
                            if prod_href not in item_cache:
                                item_cache[prod_href] = pystac.Item.from_file(prod_href)
                            derived_link.target = item_cache[prod_href]

                    if products_downloaded and not self._matchup_products_downloaded(mu_item):
                        continue
                    if properties is not None and not _properties_match(mu_item, properties):
                        continue
                    matchups.append(Matchup.from_stac_item(mu_item))

                if (products_downloaded or properties is not None) and not matchups:
                    continue

                if matchups:
                    event.matchup_set = MatchupSet(matchups)

                events.append(event)

        return events

    @staticmethod
    def _matchup_products_downloaded(mu_item: pystac.Item) -> bool:
        """Return True if every derived_from product Item has a downloaded data asset."""
        for link in mu_item.links:
            if link.rel != "derived_from":
                continue
            if isinstance(link.target, pystac.Item):
                target = link.target
            else:
                abs_href = link.get_absolute_href()
                if abs_href is None:
                    return False
                target = pystac.Item.from_file(abs_href)
            asset = target.assets.get("data")
            if asset is None or asset.extra_fields.get("scrappi:asset_state") != "downloaded":
                return False
        return True

    @staticmethod
    def _event_item_matches(
        item: pystac.Item,
        platforms: Optional[List[str]],
        start_time: Optional[dt.datetime],
        stop_time: Optional[dt.datetime],
        bbox: Optional[List[float]],
    ) -> bool:
        if platforms is not None:
            item_platforms = item.properties.get("matchup:platforms", [])
            if not any(p in item_platforms for p in platforms):
                return False

        if start_time is not None or stop_time is not None:

            def _utc(d: dt.datetime) -> dt.datetime:
                return d if d.tzinfo is not None else d.replace(tzinfo=dt.timezone.utc)

            if item.datetime is None:
                return False
            item_start = _utc(item.datetime)
            end_str = item.properties.get("end_datetime")
            item_stop = _utc(dt.datetime.fromisoformat(end_str)) if end_str else item_start
            if start_time is not None and item_stop < _utc(start_time):
                return False
            if stop_time is not None and item_start > _utc(stop_time):
                return False

        if bbox is not None:
            if item.bbox is None:
                return False
            q_lon_min, q_lat_min, q_lon_max, q_lat_max = bbox
            e_lon_min, e_lat_min, e_lon_max, e_lat_max = item.bbox
            if e_lon_max < q_lon_min or e_lon_min > q_lon_max:
                return False
            if e_lat_max < q_lat_min or e_lat_min > q_lat_max:
                return False

        return True

    def save(
        self,
        path: Optional[str] = None,
        catalog_type: pystac.CatalogType = pystac.CatalogType.SELF_CONTAINED,
    ) -> None:
        """Normalise hrefs and write the catalogue to disk.

        Items are laid out as ``{collection}/{YYYY}/{M}/{D}/{item-id}.json``
        with no per-item subdirectory.

        :param path: root directory to save to. Defaults to the path set at construction.
        :raises ValueError: if no path is available.
        """
        save_path = path or self.path
        if save_path is None:
            raise ValueError("No path provided — pass a path to save() or set one at construction.")
        # Template is relative to each collection's directory in pystac 1.x,
        # so omit ${collection} and add .json — items land at
        # {collection}/{year}/{month}/{day}/{id}.json with no double-nesting.
        strategy = pystac.layout.TemplateLayoutStrategy(item_template="${year}/${month}/${day}/${id}.json")
        self.catalog.normalize_hrefs(save_path, strategy=strategy)
        self.catalog.save(catalog_type=catalog_type)
        _fix_stac_hrefs(save_path)

    def _add_asset(self, collection_id: str, item_id: str, asset_key: str, asset: pystac.Asset) -> bool:
        """Find an item by collection and ID, set an asset on it, and save if file-backed."""
        col = self.catalog.get_child(collection_id)
        if col is None:
            return False
        item = next(col.get_items(item_id), None)
        if item is None:
            return False
        item.assets[asset_key] = asset
        if item.get_self_href() is not None:
            item.save_object()
        return True

    def add_asset_by_id(
        self,
        collection_id: str,
        item_id: str,
        asset_key: str,
        asset: pystac.Asset,
    ) -> bool:
        """Add or replace a STAC asset on an item identified by collection and item ID.

        Lower-level alternative to :py:meth:`add_matchup_asset` for use when only
        the STAC IDs are known (e.g. from a CLI or after a :py:func:`~eomatch.query.query`
        call), without a live :py:class:`~eomatch.domain.Matchup` object.

        :param collection_id: ID of the collection containing the target item.
        :param item_id: ID of the item to update.
        :param asset_key: asset key to set, e.g. ``"comparison:2026-05-12"``.
        :param asset: :py:class:`pystac.Asset` to register.
        :return: ``True`` if the item was found and updated, ``False`` if not found.
        """
        return self._add_asset(collection_id, item_id, asset_key, asset)

    def _remove_asset(
        self,
        collection_id: str,
        item_id: str,
        asset_key: str,
        delete_file: bool = True,
    ) -> bool:
        """Remove an asset from an item, optionally deleting the local file.

        The asset reference is always removed from the STAC item. If
        ``delete_file`` is ``True`` and the asset href resolves to a local
        path (not a URL), the file or directory is deleted from disk.
        """
        col = self.catalog.get_child(collection_id)
        if col is None:
            return False
        item = next(col.get_items(item_id), None)
        if item is None:
            return False
        if asset_key not in item.assets:
            return False

        if delete_file:
            href = item.assets[asset_key].href
            self_href = item.get_self_href()
            if self_href is not None and not os.path.isabs(href):
                href = os.path.normpath(os.path.join(os.path.dirname(self_href), href))
            if not urlparse(href).scheme:
                if os.path.isdir(href):
                    shutil.rmtree(href)
                elif os.path.isfile(href):
                    os.remove(href)

        del item.assets[asset_key]
        if item.get_self_href() is not None:
            item.save_object()
        return True

    def add_product_asset(
        self,
        product: ProductItem,
        asset_key: str,
        asset: pystac.Asset,
    ) -> bool:
        """Add or replace a STAC asset on a product Item in the catalogue.

        :param product: the :py:class:`~scrappi.ProductItem` whose catalogue Item to update.
        :param asset_key: asset key, e.g. ``"data"``, ``"thumbnail"``.
        :param asset: :py:class:`pystac.Asset` to register.
        :return: ``True`` if the item was found and updated, ``False`` if not found.
        """
        return self._add_asset(product.collection, product.id, asset_key, asset)

    def add_event_asset(
        self,
        event: "MatchupEvent",
        asset_key: str,
        asset: pystac.Asset,
    ) -> bool:
        """Add or replace a STAC asset on a matchup event Item in the catalogue.

        Also updates ``event.assets`` so the in-memory object stays in sync.

        :param event: the :py:class:`~eomatch.MatchupEvent` whose catalogue Item to update.
        :param asset_key: asset key, e.g. ``"thumbnail"``.
        :param asset: :py:class:`pystac.Asset` to register.
        :return: ``True`` if the item was found and updated, ``False`` if not found.
        """
        collection_id = _matchup_events_collection_id(event.collections, event.platforms)
        result = self._add_asset(collection_id, event.stac_id, asset_key, asset)
        if result:
            event.assets[asset_key] = asset
        return result

    def add_matchup_asset(
        self,
        matchup: "Matchup",
        asset_key: str,
        asset: pystac.Asset,
    ) -> bool:
        """Add or replace a STAC asset on a matchup Item in the catalogue.

        Also updates ``matchup.assets`` so the in-memory object stays in sync.

        :param matchup: the :py:class:`~eomatch.Matchup` whose catalogue Item to update.
        :param asset_key: asset key, e.g. ``"data"``, ``"thumbnail"``.
        :param asset: :py:class:`pystac.Asset` to register.
        :return: ``True`` if the item was found and updated, ``False`` if not found.
        """
        collection_id = _matchup_collection_id(
            [p.collection for p in matchup.products],
            [p.platform for p in matchup.products],
        )
        stac_id = matchup.stac_id
        assert stac_id is not None
        result = self._add_asset(collection_id, stac_id, asset_key, asset)
        if result:
            matchup.assets[asset_key] = asset
        return result

    def remove_product_asset(
        self,
        product: ProductItem,
        asset_key: str,
        delete_file: bool = True,
    ) -> bool:
        """Remove a STAC asset from a product Item, optionally deleting the local file.

        :param product: the :py:class:`~scrappi.ProductItem` whose catalogue Item to update.
        :param asset_key: asset key to remove, e.g. ``"data"``.
        :param delete_file: if ``True`` (default), delete the local file or directory
            that the asset href points to. Remote URLs are never deleted.
        :return: ``True`` if the asset was found and removed, ``False`` if the item or
            asset was not found.
        """
        return self._remove_asset(product.collection, product.id, asset_key, delete_file)

    def remove_event_asset(
        self,
        event: "MatchupEvent",
        asset_key: str,
        delete_file: bool = True,
    ) -> bool:
        """Remove a STAC asset from a matchup event Item, optionally deleting the local file.

        Also removes the key from ``event.assets`` if present.

        :param event: the :py:class:`~eomatch.MatchupEvent` whose catalogue Item to update.
        :param asset_key: asset key to remove.
        :param delete_file: if ``True`` (default), delete the local file or directory.
        :return: ``True`` if the asset was found and removed, ``False`` otherwise.
        """
        collection_id = _matchup_events_collection_id(event.collections, event.platforms)
        result = self._remove_asset(collection_id, event.stac_id, asset_key, delete_file)
        if result:
            event.assets.pop(asset_key, None)
        return result

    def remove_matchup_asset(
        self,
        matchup: "Matchup",
        asset_key: str,
        delete_file: bool = True,
    ) -> bool:
        """Remove a STAC asset from a matchup Item, optionally deleting the local file.

        Also removes the key from ``matchup.assets`` if present.

        :param matchup: the :py:class:`~eomatch.Matchup` whose catalogue Item to update.
        :param asset_key: asset key to remove.
        :param delete_file: if ``True`` (default), delete the local file or directory.
        :return: ``True`` if the asset was found and removed, ``False`` otherwise.
        """
        collection_id = _matchup_collection_id(
            [p.collection for p in matchup.products],
            [p.platform for p in matchup.products],
        )
        stac_id = matchup.stac_id
        assert stac_id is not None
        result = self._remove_asset(collection_id, stac_id, asset_key, delete_file)
        if result:
            matchup.assets.pop(asset_key, None)
        return result

    def _add_collection_asset(self, collection_id: str, asset_key: str, asset: pystac.Asset) -> bool:
        """Set an asset on a child Collection and save it if file-backed."""
        child = self.catalog.get_child(collection_id)
        if child is None:
            return False
        col = cast(pystac.Collection, child)
        col.assets[asset_key] = asset
        if col.get_self_href() is not None:
            col.save_object()
        return True

    def _remove_collection_asset(
        self,
        collection_id: str,
        asset_key: str,
        delete_file: bool = True,
    ) -> bool:
        """Remove an asset from a child Collection, optionally deleting the local file."""
        child = self.catalog.get_child(collection_id)
        if child is None:
            return False
        col = cast(pystac.Collection, child)
        if asset_key not in col.assets:
            return False
        if delete_file:
            href = col.assets[asset_key].href
            self_href = col.get_self_href()
            if self_href is not None and not os.path.isabs(href):
                href = os.path.normpath(os.path.join(os.path.dirname(self_href), href))
            if not urlparse(href).scheme:
                if os.path.isdir(href):
                    shutil.rmtree(href)
                elif os.path.isfile(href):
                    os.remove(href)
        del col.assets[asset_key]
        if col.get_self_href() is not None:
            col.save_object()
        return True

    def add_matchup_collection_asset(
        self,
        matchup: "Matchup",
        asset_key: str,
        asset: pystac.Asset,
    ) -> bool:
        """Add or replace a STAC asset on the matchup Collection (e.g. ``LANDSAT_C2L1-vs-S3_EFR``).

        Use this to attach collection-level results — aggregated statistics, processing reports,
        or any artefact that belongs to the sensor-pair collection rather than a single matchup Item.

        :param matchup: any :py:class:`~eomatch.Matchup` from the target collection; its
            product collections determine which Collection is updated.
        :param asset_key: asset key, e.g. ``"report"``.
        :param asset: :py:class:`pystac.Asset` to register.
        :return: ``True`` if the collection was found and updated, ``False`` if not found.
        """
        collection_id = _matchup_collection_id(
            [p.collection for p in matchup.products],
            [p.platform for p in matchup.products],
        )
        return self._add_collection_asset(collection_id, asset_key, asset)

    def remove_matchup_collection_asset(
        self,
        matchup: "Matchup",
        asset_key: str,
        delete_file: bool = True,
    ) -> bool:
        """Remove a STAC asset from the matchup Collection, optionally deleting the local file.

        :param matchup: any :py:class:`~eomatch.Matchup` from the target collection.
        :param asset_key: asset key to remove.
        :param delete_file: if ``True`` (default), delete the local file or directory.
        :return: ``True`` if the asset was found and removed, ``False`` otherwise.
        """
        collection_id = _matchup_collection_id(
            [p.collection for p in matchup.products],
            [p.platform for p in matchup.products],
        )
        return self._remove_collection_asset(collection_id, asset_key, delete_file)

    def add_event_collection_asset(
        self,
        event: "MatchupEvent",
        asset_key: str,
        asset: pystac.Asset,
    ) -> bool:
        """Add or replace a STAC asset on the matchup-events Collection
        (e.g. ``matchup-events-LANDSAT_C2L1-vs-S3_EFR``).

        :param event: any :py:class:`~eomatch.MatchupEvent` from the target collection; its
            collections determine which Collection is updated.
        :param asset_key: asset key, e.g. ``"summary"``.
        :param asset: :py:class:`pystac.Asset` to register.
        :return: ``True`` if the collection was found and updated, ``False`` if not found.
        """
        collection_id = _matchup_events_collection_id(event.collections, event.platforms)
        return self._add_collection_asset(collection_id, asset_key, asset)

    def remove_event_collection_asset(
        self,
        event: "MatchupEvent",
        asset_key: str,
        delete_file: bool = True,
    ) -> bool:
        """Remove a STAC asset from the matchup-events Collection, optionally deleting the local file.

        :param event: any :py:class:`~eomatch.MatchupEvent` from the target collection.
        :param asset_key: asset key to remove.
        :param delete_file: if ``True`` (default), delete the local file or directory.
        :return: ``True`` if the asset was found and removed, ``False`` otherwise.
        """
        collection_id = _matchup_events_collection_id(event.collections, event.platforms)
        return self._remove_collection_asset(collection_id, asset_key, delete_file)

    def download_products(
        self,
        event_set: Optional[MatchupEventSet] = None,
        filesystem: Optional[STACFileSystem] = None,
    ) -> List[str]:
        """Download all source products for the given events and register each
        as a ``"data"`` STAC asset on the matching product Item in the catalogue.

        Products that share an ID across multiple matchups are downloaded only
        once. Already-downloaded products (present on disk) are registered
        without re-downloading. If the catalogue is file-backed, the updated
        Item JSON is written to disk immediately after each product is handled.

        :param event_set: events whose products to download; defaults to all
            events in the catalogue via :py:meth:`get_events`.
        :param filesystem: filesystem to download into; defaults to the
            ``product_fs`` set at construction.
        :return: list of paths to the downloaded (or already-present) product files.
        """
        fs = filesystem or self.product_fs
        if event_set is None:
            event_set = self.get_events()

        downloaded: List[str] = []
        seen: set = set()

        for event in event_set:
            if event.matchup_set is None:
                continue
            for matchup in event.matchup_set:
                for product in matchup.products:
                    if product.id in seen:
                        continue
                    seen.add(product.id)

                    if fs is not None:
                        product.set_fs(fs)

                    existing_path, exists = product.filesystem.return_path(product, check_exists=True)
                    if exists:
                        path = existing_path
                    else:
                        path = product.download_product()
                        if path is None:
                            continue
                    downloaded.append(path)

                    col = self.catalog.get_child(product.collection)
                    if col is None:
                        continue
                    item = next(col.get_items(product.id), None)
                    if item is None:
                        continue

                    self_href = item.get_self_href()
                    href = os.path.relpath(path, os.path.dirname(self_href)) if self_href is not None else path
                    item.assets["data"] = pystac.Asset(
                        href=href,
                        media_type="application/octet-stream",
                        title="data",
                        extra_fields={"scrappi:asset_state": "downloaded"},
                    )
                    if self_href is not None:
                        item.save_object()

        return downloaded

    @classmethod
    def open(cls, path: str) -> "MatchupCatalogue":
        """Open an existing catalogue from a root ``catalog.json`` path.

        The catalogue root directory is inferred from ``path`` and used to
        initialise ``product_fs`` so that :py:meth:`download_products` works
        without further configuration.
        """
        if os.path.isdir(path):
            path = os.path.join(path, "catalog.json")
        root_dir = os.path.dirname(os.path.abspath(path))
        _fix_stac_hrefs(root_dir)
        catalog = pystac.Catalog.from_file(path)
        return cls(catalog=catalog, path=root_dir)
