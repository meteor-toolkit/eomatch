"""eomatch.query — pull items from a remote STAC API to a local pystac catalogue."""

import argparse
import datetime as dt
import logging
import os
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

import pystac
import pystac.layout

from eomatch import EOMatchContext

__all__ = ["query"]

log = logging.getLogger(__name__)


def _item_id_from_href(href: str) -> Optional[str]:
    """Extract a STAC item ID from a link href.

    Works with HTTP URLs, broken HTTP URLs, and relative file paths.  The
    item ID is assumed to be the last path segment, minus any ``.json``
    extension.

    :param href: link href string to parse.
    :return: the last path segment without ``.json``, or ``None`` if *href*
        is empty or has no usable segment.
    """
    if not href:
        return None
    path = urlparse(href).path.rstrip("/")
    segment = path.split("/")[-1] if path else ""
    if segment.endswith(".json"):
        segment = segment[:-5]
    return segment or None


def _collect_missing_ids(catalog: pystac.Catalog, known_ids: Set[str]) -> Set[str]:
    """Return IDs referenced by related/derived_from links but absent from *known_ids*.

    Inspects every item in *catalog* and collects the target IDs of any
    ``related`` or ``derived_from`` links whose target item is not yet in the
    catalogue.

    :param catalog: catalogue to inspect.
    :param known_ids: set of item IDs already present in the catalogue.
    :return: set of item IDs that are referenced but not yet fetched.
    """
    missing: Set[str] = set()
    for item in catalog.get_items(recursive=True):
        for link in item.links:
            if link.rel not in ("related", "derived_from"):
                continue
            item_id: Optional[str]
            if isinstance(link.target, pystac.Item):
                item_id = link.target.id
            else:
                item_id = _item_id_from_href(link.href or "")
            if item_id and item_id not in known_ids:
                missing.add(item_id)
    return missing


def _rewrite_cross_item_links(catalog: pystac.Catalog) -> None:
    """Rewrite related/derived_from link hrefs to correct relative local paths.

    Must be called after :py:meth:`pystac.Catalog.normalize_hrefs` has
    assigned local file paths to all items.  Converts any absolute HTTP URLs
    or stale relative paths in ``related``/``derived_from`` links to relative
    paths between local files, so that
    :py:meth:`~eomatch.mu_stac.MatchupCatalogue.get_events` can follow
    them without network access.

    Links whose target item is not present in the catalogue are left unchanged.

    :param catalog: catalogue whose item links should be rewritten in-place.
    """
    id_to_path: Dict[str, str] = {
        item.id: href for item in catalog.get_items(recursive=True) if (href := item.get_self_href()) is not None
    }
    for item in catalog.get_items(recursive=True):
        self_href = item.get_self_href()
        if not self_href:
            continue
        item_dir = os.path.dirname(self_href)
        for link in item.links:
            if link.rel not in ("related", "derived_from"):
                continue
            target_id: Optional[str]
            if isinstance(link.target, pystac.Item):
                target_id = link.target.id
            else:
                target_id = _item_id_from_href(link.href or "")
            if target_id and target_id in id_to_path:
                link.target = os.path.relpath(id_to_path[target_id], item_dir)


def query(
    api_url: str,
    output_path: str,
    collections: Optional[List[str]] = None,
    start_time: Optional[dt.datetime] = None,
    end_time: Optional[dt.datetime] = None,
    bbox: Optional[List[float]] = None,
    filter_expr: Optional[str] = None,
    filter_lang: str = "cql2-text",
    config=None,
) -> pystac.Catalog:
    """Pull items from a STAC API and write them to a local pystac catalogue.

    Searches the STAC API at *api_url* using the supplied filters and writes
    matching items to *output_path* in the same on-disk layout that
    :py:class:`~eomatch.mu_stac.MatchupCatalogue` produces, so the result
    can be opened immediately with ``MatchupCatalogue.open()``.

    Items referenced via ``related`` or ``derived_from`` links (matchup items
    and source product items) are fetched automatically even if they are not
    in the requested collections, so that
    :py:meth:`~eomatch.mu_stac.MatchupCatalogue.get_events` works on the
    result without requiring network access.

    If a catalogue already exists at *output_path* (from a previous run or
    from :py:func:`~eomatch.find_and_catalogue.find_and_catalogue`), new
    items are merged in and the catalogue is resaved. Existing items are
    replaced with the API version (upsert semantics).

    Requires the ``pystac_client`` package (``pip install eomatch[query]``).

    Example usage::

        from eomatch.query import query

        query(
            api_url="http://my-server:8000/external/",
            output_path="/data/my_matchups",
            collections=["LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A"],
            start_time=datetime(2022, 1, 1),
            end_time=datetime(2022, 12, 31),
            filter_expr="time_diff_s < 900 AND land_fraction < 0.2",
        )

    :param api_url: base URL of the STAC API to query (e.g.
        ``http://server:8000/external/``).
    :param output_path: directory to write the local catalogue into.
    :param collections: restrict results to these collection IDs.  Queries
        all collections if ``None``.
    :param start_time: include only items whose datetime is at or after this
        value.
    :param end_time: include only items whose datetime is at or before this
        value.
    :param bbox: spatial filter as ``[min_lon, min_lat, max_lon, max_lat]``.
    :param filter_expr: CQL2 filter expression applied server-side, e.g.
        ``"time_diff_s < 900 AND land_fraction < 0.2"``.  Requires the STAC
        API to support the ``filter`` extension (pgSTAC does).
    :param filter_lang: filter language identifier; ``"cql2-text"`` (default)
        or ``"cql2-json"``.
    :param config: path to a eomatch YAML config file, or a dict of
        overrides.  Loaded for default settings but all parameters above take
        precedence.
    :return: the resulting :py:class:`pystac.Catalog` (also saved to disk).
    """
    try:
        from pystac_client import Client
    except ImportError:
        raise ImportError("pystac_client is required for query. Install it with: pip install 'eomatch[query]'")

    ctx = EOMatchContext(config) if config else EOMatchContext()
    query_cfg = ctx.get("query") or {}
    _api_url = api_url or query_cfg.get("api_url")
    if not _api_url:
        raise ValueError("No API URL supplied. Pass api_url= or set query.api_url in config.")

    log.info("Connecting to STAC API: %s", _api_url)
    client = Client.open(_api_url)

    search_kwargs: dict = {}
    if collections:
        search_kwargs["collections"] = collections
    if start_time or end_time:
        t_start = start_time.isoformat() if start_time else ".."
        t_end = end_time.isoformat() if end_time else ".."
        search_kwargs["datetime"] = f"{t_start}/{t_end}"
    if bbox:
        search_kwargs["bbox"] = bbox
    if filter_expr:
        search_kwargs["filter"] = filter_expr
        search_kwargs["filter_lang"] = filter_lang

    search = client.search(**search_kwargs)
    log.info("Searching with filters: %s", search_kwargs or "(none)")

    # Load or create the local catalogue.
    catalog_json = os.path.join(output_path, "catalog.json")
    if os.path.exists(catalog_json):
        log.info("Updating existing catalogue at %s", output_path)
        catalog = pystac.Catalog.from_file(catalog_json)
    else:
        os.makedirs(output_path, exist_ok=True)
        catalog = pystac.Catalog(id="matchup-catalogue", description="EOMatch catalogue")
        log.info("Creating new catalogue at %s", output_path)

    # Build a lookup of existing collections so we can upsert items.
    col_index: Dict[str, pystac.Collection] = {
        c.id: c for c in catalog.get_children() if isinstance(c, pystac.Collection)
    }

    def _get_or_create_collection(collection_id: str) -> pystac.Collection:
        if collection_id in col_index:
            return col_index[collection_id]
        _none_interval: List[List[Optional[dt.datetime]]] = [[None, None]]
        col = pystac.Collection(
            id=collection_id,
            description=collection_id,
            extent=pystac.Extent(
                spatial=pystac.SpatialExtent(bboxes=[[-180.0, -90.0, 180.0, 90.0]]),
                temporal=pystac.TemporalExtent(intervals=_none_interval),
            ),
        )
        catalog.add_child(col)
        col_index[collection_id] = col
        return col

    n_added = n_updated = 0
    for item_dict in search.items_as_dicts():
        collection_id = item_dict.get("collection", "uncollected")
        col = _get_or_create_collection(collection_id)

        item = pystac.Item.from_dict(item_dict)

        # Upsert: replace any existing item with the same ID.
        existing = next(col.get_items(item.id), None)
        if existing is not None:
            col.remove_item(item.id)
            n_updated += 1
        else:
            n_added += 1
        col.add_item(item)

    total = n_added + n_updated
    log.info("Fetched %d item(s) (%d new, %d updated)", total, n_added, n_updated)

    # Iteratively fetch items referenced via related/derived_from links.
    # This pulls in matchup items and source product items so that
    # MatchupCatalogue.get_events() can follow links locally without hitting the
    # network. Cap at 10 passes to handle deep reference chains.
    known_ids: Set[str] = {item.id for item in catalog.get_items(recursive=True)}
    for _ in range(10):
        missing = _collect_missing_ids(catalog, known_ids)
        if not missing:
            break
        log.info("Fetching %d referenced item(s) not in initial results", len(missing))
        n_ref = 0
        for item_dict in client.search(ids=list(missing)).items_as_dicts():
            item = pystac.Item.from_dict(item_dict)
            collection_id = item.collection_id or "uncollected"
            col = _get_or_create_collection(collection_id)
            existing = next(col.get_items(item.id), None)
            if existing is not None:
                col.remove_item(item.id)
            col.add_item(item)
            known_ids.add(item.id)
            n_ref += 1
        if n_ref == 0:
            log.warning(
                "%d referenced item(s) not found in the API — cross-item links may be broken",
                len(missing),
            )
            break

    # Template is relative to each collection's directory (pystac 1.x behaviour),
    # so omit ${collection} here — items land at {collection}/{year}/{month}/{day}/{id}.json.
    strategy = pystac.layout.TemplateLayoutStrategy(item_template="${year}/${month}/${day}/${id}.json")
    catalog.normalize_hrefs(output_path, strategy=strategy)

    # Rewrite cross-item links to relative local paths. Items from the API carry
    # these links as HTTP URLs resolved against the API's item endpoints, which
    # are not valid local paths.
    _rewrite_cross_item_links(catalog)

    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    log.info("Catalogue saved to %s", output_path)

    return catalog


def main() -> None:
    """CLI entry point for ``eomatch-query``."""
    parser = argparse.ArgumentParser(
        description=(
            "Pull items from a remote STAC API and write them to a local "
            "pystac catalogue that the eomatch toolchain can work with."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--api-url",
        required=True,
        metavar="URL",
        help="Base URL of the STAC API (e.g. http://server:8000/external/)",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="PATH",
        help="Directory to write the local catalogue into",
    )
    parser.add_argument("--config", metavar="PATH", help="EOMatch YAML config file")
    parser.add_argument(
        "--collections",
        metavar="ID",
        nargs="+",
        help="Restrict results to these collection IDs",
    )
    parser.add_argument(
        "--start-time",
        metavar="DATETIME",
        help="Include only items at or after this ISO-8601 datetime",
    )
    parser.add_argument(
        "--end-time",
        metavar="DATETIME",
        help="Include only items at or before this ISO-8601 datetime",
    )
    parser.add_argument(
        "--bbox",
        metavar="FLOAT",
        nargs=4,
        type=float,
        help="Spatial filter: min_lon min_lat max_lon max_lat",
    )
    parser.add_argument(
        "--filter",
        metavar="EXPR",
        dest="filter_expr",
        help=(
            "CQL2 filter expression applied server-side, e.g. "
            '"time_diff_s < 900 AND land_fraction < 0.2". '
            "Requires the STAC API to support the filter extension (pgSTAC does)."
        ),
    )
    parser.add_argument(
        "--filter-lang",
        metavar="LANG",
        default="cql2-text",
        choices=["cql2-text", "cql2-json"],
        help="Filter language: cql2-text (default) or cql2-json.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    start_time = dt.datetime.fromisoformat(args.start_time) if args.start_time else None
    end_time = dt.datetime.fromisoformat(args.end_time) if args.end_time else None

    query(
        api_url=args.api_url,
        output_path=args.output,
        collections=args.collections,
        start_time=start_time,
        end_time=end_time,
        bbox=args.bbox,
        filter_expr=args.filter_expr,
        filter_lang=args.filter_lang,
        config=args.config,
    )


if __name__ == "__main__":
    main()
