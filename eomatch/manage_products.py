"""eomatch.manage_products - download and remove catalogue products"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
from typing import List, Optional

from eomatch.context import EOMatchContext
from eomatch.mu_stac import MatchupCatalogue

log = logging.getLogger(__name__)


def _open_catalogue(path: Optional[str], context: EOMatchContext) -> MatchupCatalogue:
    """Resolve a catalogue path and open the catalogue.

    :param path: explicit path to a catalogue root directory or ``catalog.json``; takes
        precedence over the context config.
    :param context: used to read ``matchup_catalogue.path`` when ``path`` is ``None``.
    :return: open :py:class:`~eomatch.mu_stac.MatchupCatalogue`.
    :raises ValueError: if no catalogue path can be determined.
    """
    _path = path
    if _path is None:
        cfg = context.get("matchup_catalogue") or {}
        _path = cfg.get("path")
    if _path is None:
        raise ValueError("No catalogue path provided — pass a path or set matchup_catalogue.path in config.")
    if os.path.isdir(_path):
        _path = os.path.join(_path, "catalog.json")
    return MatchupCatalogue.open(_path)


def _parse_filter_args(args: argparse.Namespace) -> dict:
    """Convert CLI args to get_events filter kwargs."""
    return dict(
        collections=args.collections.split(",") if args.collections else None,
        platforms=args.platforms.split(",") if args.platforms else None,
        start_time=(dt.datetime.fromisoformat(args.start_time) if args.start_time else None),
        stop_time=dt.datetime.fromisoformat(args.stop_time) if args.stop_time else None,
        bbox=[float(x) for x in args.bbox.split(",")] if args.bbox else None,
    )


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add shared catalogue path, filter, and logging arguments to a parser."""
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to a YAML config file. Merged on top of the user config.",
    )
    parser.add_argument(
        "--path",
        metavar="PATH",
        help="Catalogue root directory or catalog.json path. Overrides matchup_catalogue.path in config.",
    )
    parser.add_argument(
        "--collections",
        metavar="C1,C2",
        help="Comma-separated collection names to filter by, e.g. LANDSAT_C2L1,S2_MSI_L1C.",
    )
    parser.add_argument(
        "--platforms",
        metavar="P1,P2",
        help="Comma-separated platform names to filter by.",
    )
    parser.add_argument(
        "--start-time",
        metavar="DATETIME",
        help="ISO 8601 start-time filter (events ending before this are excluded).",
    )
    parser.add_argument(
        "--stop-time",
        metavar="DATETIME",
        help="ISO 8601 stop-time filter (events starting after this are excluded).",
    )
    parser.add_argument(
        "--bbox",
        metavar="LON_MIN,LAT_MIN,LON_MAX,LAT_MAX",
        help="Spatial bounding-box filter as four comma-separated floats.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")


def download_catalogue_products(
    context: Optional[EOMatchContext] = None,
    path: Optional[str] = None,
    collections: Optional[List[str]] = None,
    platforms: Optional[List[str]] = None,
    start_time: Optional[dt.datetime] = None,
    stop_time: Optional[dt.datetime] = None,
    bbox: Optional[List[float]] = None,
) -> List[str]:
    """Download source products for catalogue events matching the given filters.

    Opens the existing catalogue, queries for matching events, downloads all
    source products and registers a ``"data"`` STAC asset on each product Item.
    Products already present on disk are registered without re-downloading.

    :param context: shared configuration; defaults to ``EOMatchContext()``.
    :param path: catalogue root directory or ``catalog.json`` path. Overrides
        ``matchup_catalogue.path`` in config when provided.
    :param collections: restrict to one sensor pair, e.g. ``["LANDSAT_C2L1", "S2_MSI_L1C"]``.
    :param platforms: restrict to events that include at least one of these platforms.
    :param start_time: exclude events whose stop time is before this datetime.
    :param stop_time: exclude events whose start time is after this datetime.
    :param bbox: spatial filter as ``[lon_min, lat_min, lon_max, lat_max]``.
    :return: list of paths to downloaded (or already-present) product files.
    """
    if context is None:
        context = EOMatchContext()

    catalogue = _open_catalogue(path, context)

    log.info("Querying catalogue for matching events...")
    event_set = catalogue.get_events(
        collections=collections,
        platforms=platforms,
        start_time=start_time,
        stop_time=stop_time,
        bbox=bbox,
    )
    n_matchups = sum(len(e.matchup_set) for e in event_set if e.matchup_set is not None)
    log.info("Found %d event(s) containing %d matchup(s)", len(event_set), n_matchups)

    log.info("Downloading products...")
    downloaded = catalogue.download_products(event_set=event_set)
    log.info("Done — %d product(s) handled.", len(downloaded))

    return downloaded


def remove_catalogue_products(
    context: Optional[EOMatchContext] = None,
    path: Optional[str] = None,
    collections: Optional[List[str]] = None,
    platforms: Optional[List[str]] = None,
    start_time: Optional[dt.datetime] = None,
    stop_time: Optional[dt.datetime] = None,
    bbox: Optional[List[float]] = None,
    delete_files: bool = True,
) -> int:
    """Remove downloaded product files for catalogue events matching the given filters.

    Removes the ``"data"`` STAC asset from each matching product Item. If
    ``delete_files`` is ``True``, the local file or directory is also deleted
    from disk. Products shared across multiple matchups are processed only once.

    :param context: shared configuration; defaults to ``EOMatchContext()``.
    :param path: catalogue root directory or ``catalog.json`` path. Overrides
        ``matchup_catalogue.path`` in config when provided.
    :param collections: restrict to one sensor pair, e.g. ``["LANDSAT_C2L1", "S2_MSI_L1C"]``.
    :param platforms: restrict to events that include at least one of these platforms.
    :param start_time: exclude events whose stop time is before this datetime.
    :param stop_time: exclude events whose start time is after this datetime.
    :param bbox: spatial filter as ``[lon_min, lat_min, lon_max, lat_max]``.
    :param delete_files: if ``True`` (default), delete the local file or directory
        that the asset href points to. Remote URLs are never deleted.
    :return: number of product assets removed.
    """
    if context is None:
        context = EOMatchContext()

    catalogue = _open_catalogue(path, context)

    log.info("Querying catalogue for events with downloaded products...")
    event_set = catalogue.get_events(
        collections=collections,
        platforms=platforms,
        start_time=start_time,
        stop_time=stop_time,
        bbox=bbox,
        products_downloaded=True,
    )
    n_matchups = sum(len(e.matchup_set) for e in event_set if e.matchup_set is not None)
    log.info(
        "Found %d event(s) containing %d matchup(s) with downloaded products",
        len(event_set),
        n_matchups,
    )

    removed = 0
    seen: set = set()
    for event in event_set:
        if event.matchup_set is None:
            continue
        for matchup in event.matchup_set:
            for product in matchup.products:
                if product.id in seen:
                    continue
                seen.add(product.id)
                if catalogue.remove_product_asset(product, "data", delete_file=delete_files):
                    removed += 1
                    log.debug("Removed data asset for product %s", product.id)

    log.info("Done — removed %d product asset(s).", removed)
    return removed


def _main_download() -> None:
    """Entry point for the ``eomatch-download`` console script."""
    parser = argparse.ArgumentParser(description="Download catalogue products matching filter criteria.")
    _add_common_args(parser)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    context = EOMatchContext(args.config) if args.config else EOMatchContext()
    download_catalogue_products(context=context, path=args.path, **_parse_filter_args(args))


def _main_remove() -> None:
    """Entry point for the ``eomatch-remove`` console script."""
    parser = argparse.ArgumentParser(description="Remove downloaded catalogue products matching filter criteria.")
    _add_common_args(parser)
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Remove asset references from the catalogue without deleting local files.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    context = EOMatchContext(args.config) if args.config else EOMatchContext()
    remove_catalogue_products(
        context=context,
        path=args.path,
        delete_files=not args.keep_files,
        **_parse_filter_args(args),
    )
