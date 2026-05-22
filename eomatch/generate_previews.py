"""eomatch.generate_previews - generate and catalogue preview thumbnails for matchups"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
from typing import List, Optional

import matplotlib.pyplot as plt
import pystac

from eomatch.context import EOMatchContext
from eomatch.domain import _matchup_collection_id, _matchup_events_collection_id
from eomatch.mu_stac import MatchupCatalogue
from eomatch.preview import BuildMUPreview, build_event_geo_thumbnail, preview_event

log = logging.getLogger(__name__)

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = ["generate_previews"]


def generate_previews(
    catalogue_path: str,
    collections: Optional[List[str]] = None,
    platforms: Optional[List[str]] = None,
    start_time: Optional[dt.datetime] = None,
    stop_time: Optional[dt.datetime] = None,
    bbox: Optional[List[float]] = None,
    max_pixels: int = 512,
    overwrite: bool = False,
    generate_thumbnail: bool = True,
    generate_overview: bool = True,
    generate_event_thumbnail: bool = True,
    generate_event_overview: bool = True,
    context: Optional[EOMatchContext] = None,
) -> int:
    """Generate preview thumbnails for matchups and events in a STAC catalogue.

    For each matchup item, optionally generates:

    - A side-by-side PNG thumbnail (``"thumbnail"`` asset) showing imagery from
      each sensor.
    - A georeferenced RGBA GeoTIFF overview (``"overview"`` asset) that STAC
      Browser renders on the slippy map.

    For each matchup event item, optionally generates:

    - A PNG thumbnail (``"thumbnail"`` asset) showing product footprints coloured
      by collection.
    - A georeferenced RGBA GeoTIFF overview (``"overview"`` asset) with
      semi-transparent polygon footprints, suitable for overlay on the slippy map.

    Only matchup assets for events whose source products have already been
    downloaded are generated.  Event assets are generated whenever a matchup set
    is present.  Assets that already exist are skipped unless ``overwrite=True``.
    Each asset is saved to the ``thumbnails/`` tree inside the catalogue and the
    item JSON is updated on disk immediately.

    Intended as a periodic job: running it repeatedly on the same catalogue is
    safe — already-generated items are left untouched.

    Example usage::

        from eomatch.generate_previews import generate_previews

        n = generate_previews("/path/to/catalogue", max_pixels=256)
        n = generate_previews("/path/to/catalogue", generate_overview=True)

    :param catalogue_path: path to the root ``catalog.json`` of an existing
        :py:class:`~eomatch.mu_stac.MatchupCatalogue`.
    :param collections: restrict to one sensor pair,
        e.g. ``["S2_MSI_L1C", "LANDSAT_C2L1"]``.
    :param platforms: return only events that include at least one of these
        platforms.
    :param start_time: lower bound on event time (inclusive).
    :param stop_time: upper bound on event time (inclusive).
    :param bbox: spatial filter as ``[lon_min, lat_min, lon_max, lat_max]``.
    :param max_pixels: maximum pixel extent in either spatial dimension of the
        generated assets.
    :param overwrite: if ``True``, regenerate assets even when they already
        exist.
    :param generate_thumbnail: if ``True`` (default), generate the side-by-side
        PNG thumbnail for matchups and register it as a ``"thumbnail"`` asset.
    :param generate_overview: if ``True`` (default), generate a georeferenced
        RGBA GeoTIFF overview for matchups and register it as an ``"overview"``
        asset.  STAC Browser renders this asset on the slippy map.
    :param generate_event_thumbnail: if ``True`` (default), generate a polygon
        footprint PNG thumbnail for events and register it as a ``"thumbnail"``
        asset.
    :param generate_event_overview: if ``True`` (default), generate a
        georeferenced RGBA GeoTIFF polygon overview for events and register it
        as an ``"overview"`` asset.
    :param context: optional :py:class:`~eomatch.context.EOMatchContext`
        supplying the ``preview.read`` config; defaults to
        ``EOMatchContext()``.
    :return: number of assets generated (all asset types combined).
    """
    mu_cat = MatchupCatalogue.open(path=catalogue_path)
    assert mu_cat.path is not None
    events = mu_cat.get_events(
        collections=collections,
        platforms=platforms,
        start_time=start_time,
        stop_time=stop_time,
        bbox=bbox,
        products_downloaded=True,
    )

    builder = BuildMUPreview(context=context)
    count = 0

    for event in events:
        if event.matchup_set is None:
            continue

        # ---- event-level thumbnails ----
        events_collection_id = _matchup_events_collection_id(event.collections, event.platforms)
        events_col = mu_cat.catalog.get_child(events_collection_id)
        event_item = next(events_col.get_items(event.stac_id), None) if events_col else None

        if event_item is not None:
            event_item_href = event_item.get_self_href()
            if event_item_href is not None:
                event_item_dt = event_item.datetime
                if event_item_dt is None:
                    continue
                event_asset_dir = os.path.join(
                    mu_cat.path,
                    "thumbnails",
                    events_collection_id,
                    event_item_dt.strftime("%Y"),
                    event_item_dt.strftime("%m"),
                    event_item_dt.strftime("%d"),
                )
                os.makedirs(event_asset_dir, exist_ok=True)
                event_item_dir = os.path.dirname(event_item_href)

                if generate_event_thumbnail and ("thumbnail" not in event_item.assets or overwrite):
                    event_thumb_path = os.path.join(event_asset_dir, f"{event.stac_id}_thumbnail.png")
                    event_thumb_href = os.path.relpath(event_thumb_path, event_item_dir)
                    try:
                        fig = preview_event(event, output_path=event_thumb_path)
                        plt.close(fig)
                        asset = pystac.Asset(
                            href=event_thumb_href,
                            media_type=pystac.MediaType.PNG,
                            title="Event footprint thumbnail",
                            roles=["thumbnail"],
                        )
                        mu_cat.add_event_asset(event, "thumbnail", asset)
                        count += 1
                        log.info(
                            "Event thumbnail saved for %s → %s",
                            event.stac_id,
                            event_thumb_path,
                        )
                    except Exception as exc:
                        log.warning(
                            "Failed to generate event thumbnail for %s: %s",
                            event.stac_id,
                            exc,
                        )
                elif generate_event_thumbnail:
                    log.debug(
                        "Skipping event thumbnail for %s — already exists",
                        event.stac_id,
                    )

                if generate_event_overview and ("overview" not in event_item.assets or overwrite):
                    event_overview_path = os.path.join(event_asset_dir, f"{event.stac_id}_overview.tif")
                    event_overview_href = os.path.relpath(event_overview_path, event_item_dir)
                    try:
                        build_event_geo_thumbnail(event, event_overview_path, max_pixels=max_pixels)
                        asset = pystac.Asset(
                            href=event_overview_href,
                            media_type="image/tiff; application=geotiff",
                            title="Event georeferenced overview",
                            roles=["overview"],
                        )
                        mu_cat.add_event_asset(event, "overview", asset)
                        count += 1
                        log.info(
                            "Event overview saved for %s → %s",
                            event.stac_id,
                            event_overview_path,
                        )
                    except Exception as exc:
                        log.warning(
                            "Failed to generate event overview for %s: %s",
                            event.stac_id,
                            exc,
                        )
                elif generate_event_overview:
                    log.debug("Skipping event overview for %s — already exists", event.stac_id)

        for matchup in event.matchup_set:
            collection_id = _matchup_collection_id(
                [p.collection for p in matchup.products],
                [p.platform for p in matchup.products],
            )
            col = mu_cat.catalog.get_child(collection_id)
            if col is None:
                log.warning("Collection %s not found in catalogue", collection_id)
                continue

            item = next(col.get_items(matchup.stac_id), None)
            if item is None:
                log.warning("Item %s not found in collection %s", matchup.stac_id, collection_id)
                continue

            item_href = item.get_self_href()
            if item_href is None:
                log.warning(
                    "Item %s has no self href — cannot determine where to save assets",
                    matchup.stac_id,
                )
                continue

            # Shared output directory mirroring the data/ folder hierarchy:
            # thumbnails/<matchup_collection>/<year>/<month>/<day>/
            item_dt = item.datetime
            if item_dt is None:
                continue
            asset_dir = os.path.join(
                mu_cat.path,
                "thumbnails",
                collection_id,
                item_dt.strftime("%Y"),
                item_dt.strftime("%m"),
                item_dt.strftime("%d"),
            )
            os.makedirs(asset_dir, exist_ok=True)

            item_dir = os.path.dirname(item_href)

            # --- side-by-side PNG thumbnail ---
            if generate_thumbnail and ("thumbnail" not in item.assets or overwrite):
                thumbnail_path = os.path.join(asset_dir, f"{matchup.stac_id}_thumbnail.png")
                thumbnail_href = os.path.relpath(thumbnail_path, item_dir)
                try:
                    fig = builder.run(matchup, output_path=thumbnail_path, max_pixels=max_pixels)
                    plt.close(fig)
                    asset = pystac.Asset(
                        href=thumbnail_href,
                        media_type=pystac.MediaType.PNG,
                        title="Preview thumbnail",
                        roles=["thumbnail"],
                    )
                    mu_cat.add_matchup_asset(matchup, "thumbnail", asset)
                    count += 1
                    log.info("Thumbnail saved for %s → %s", matchup.stac_id, thumbnail_path)
                except Exception as exc:
                    log.warning("Failed to generate thumbnail for %s: %s", matchup.stac_id, exc)
            elif generate_thumbnail:
                log.debug("Skipping thumbnail for %s — already exists", matchup.stac_id)

            # --- georeferenced RGBA GeoTIFF overview ---
            if generate_overview:
                if "overview" not in item.assets or overwrite:
                    overview_path = os.path.join(asset_dir, f"{matchup.stac_id}_overview.tif")
                    overview_href = os.path.relpath(overview_path, item_dir)
                    try:
                        builder.build_geo_thumbnail(matchup, overview_path, max_pixels=max_pixels)
                        asset = pystac.Asset(
                            href=overview_href,
                            media_type="image/tiff; application=geotiff",
                            title="Georeferenced overview",
                            roles=["overview"],
                        )
                        mu_cat.add_matchup_asset(matchup, "overview", asset)
                        count += 1
                        log.info("Overview saved for %s → %s", matchup.stac_id, overview_path)
                    except Exception as exc:
                        log.warning(
                            "Failed to generate overview for %s: %s",
                            matchup.stac_id,
                            exc,
                        )
                else:
                    log.debug("Skipping overview for %s — already exists", matchup.stac_id)

    log.info("Generated %d thumbnail(s).", count)
    return count


def main() -> None:
    """Entry point for the ``eomatch-preview`` console script."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate preview thumbnails for downloaded matchups in a STAC catalogue "
            "and register them as thumbnail assets."
        )
    )
    parser.add_argument(
        "catalogue",
        metavar="CATALOGUE",
        help="Path to the root catalog.json of the matchup catalogue.",
    )
    parser.add_argument(
        "--collections",
        metavar="ID",
        nargs="+",
        help="Restrict to this sensor pair, e.g. S2_MSI_L1C LANDSAT_C2L1.",
    )
    parser.add_argument(
        "--platforms",
        metavar="NAME",
        nargs="+",
        help="Restrict to events that include at least one of these platforms.",
    )
    parser.add_argument(
        "--start",
        metavar="DATETIME",
        help="Lower bound on event time (ISO-8601, e.g. 2022-01-01).",
    )
    parser.add_argument(
        "--stop",
        metavar="DATETIME",
        help="Upper bound on event time (ISO-8601, e.g. 2022-12-31).",
    )
    parser.add_argument(
        "--bbox",
        metavar="FLOAT",
        nargs=4,
        type=float,
        help="Spatial filter: lon_min lat_min lon_max lat_max.",
    )
    parser.add_argument(
        "--max-pixels",
        metavar="N",
        type=int,
        default=512,
        help="Maximum pixel extent in either dimension (default: 512).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate assets even when they already exist.",
    )
    parser.add_argument(
        "--no-thumbnail",
        action="store_true",
        help="Skip generating the side-by-side PNG thumbnail.",
    )
    parser.add_argument(
        "--no-overview",
        action="store_true",
        help="Skip generating the georeferenced RGBA GeoTIFF overview.",
    )
    parser.add_argument(
        "--no-event-thumbnail",
        action="store_true",
        help="Skip generating the event footprint PNG thumbnail.",
    )
    parser.add_argument(
        "--no-event-overview",
        action="store_true",
        help="Skip generating the event georeferenced RGBA GeoTIFF overview.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to a YAML config file (merged on top of the user config).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    start_time = dt.datetime.fromisoformat(args.start) if args.start else None
    stop_time = dt.datetime.fromisoformat(args.stop) if args.stop else None

    context = EOMatchContext(args.config) if args.config else EOMatchContext()

    generate_previews(
        catalogue_path=args.catalogue,
        collections=args.collections,
        platforms=args.platforms,
        start_time=start_time,
        stop_time=stop_time,
        bbox=args.bbox,
        max_pixels=args.max_pixels,
        overwrite=args.overwrite,
        generate_thumbnail=not args.no_thumbnail,
        generate_overview=not args.no_overview,
        generate_event_thumbnail=not args.no_event_thumbnail,
        generate_event_overview=not args.no_event_overview,
        context=context,
    )


if __name__ == "__main__":
    main()
