"""eomatch.add_asset — register analysis outputs as versioned STAC assets."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
from typing import Optional

import pystac

from eomatch import EOMatchContext
from eomatch.mu_stac import MatchupCatalogue

__all__ = ["register_analysis"]

log = logging.getLogger(__name__)

_MEDIA_TYPES = {
    ".nc": "application/x-netcdf",
    ".zarr": "application/vnd.zarr",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".csv": "text/csv",
}


def _detect_media_type(path: str) -> str:
    """Return a MIME type string for *path* based on its file extension.

    Falls back to ``application/octet-stream`` for unrecognised extensions.

    :param path: file path whose extension is used for the lookup.
    :return: MIME type string.
    """
    ext = os.path.splitext(path)[-1].lower()
    return _MEDIA_TYPES.get(ext, "application/octet-stream")


def register_analysis(
    catalogue_path: str,
    collection_id: str,
    item_id: str,
    file_path: str,
    key_prefix: str = "comparison",
    date: Optional[dt.date] = None,
    media_type: Optional[str] = None,
    title: Optional[str] = None,
    push: bool = False,
    config=None,
    db_host: Optional[str] = None,
    db_port: Optional[int] = None,
    db_name: Optional[str] = None,
    db_user: Optional[str] = None,
    db_password: Optional[str] = None,
    assets_base_url: Optional[str] = None,
) -> None:
    """Register an analysis output file as versioned STAC assets on a matchup item.

    Adds two assets to the item in the local catalogue:

    - ``{key_prefix}:{YYYY-MM-DD}`` — dated snapshot, never overwritten by future runs.
    - ``{key_prefix}:latest`` — always updated to point at the most recent file.

    The local catalogue JSON is written immediately.  Pass ``push=True`` to also
    upsert the updated item into the running pgSTAC database.

    Example::

        from eomatch.add_asset import register_analysis

        register_analysis(
            catalogue_path="/data/catalogue",
            collection_id="LANDSAT_C2L1-Landsat-8-vs-S2_MSI_L1C-S2A",
            item_id="L8-S2A-20220613T001234",
            file_path="/data/results/comparison_20260512.nc",
            push=True,
            db_host="localhost",
            db_name="eomatch",
        )

    :param catalogue_path: path to the root catalogue directory or ``catalog.json``.
    :param collection_id: STAC collection ID containing the target item.
    :param item_id: STAC item ID to attach the asset to.
    :param file_path: path to the analysis output file.
    :param key_prefix: prefix for the asset keys; defaults to ``"comparison"``.
    :param date: date for the dated snapshot key; defaults to today.
    :param media_type: MIME type for the asset; auto-detected from extension if ``None``.
    :param title: human-readable title for the asset; defaults to the filename.
    :param push: if ``True``, upsert the updated item into pgSTAC after saving locally.
    :param config: path to a eomatch YAML config file, or a dict of overrides.
    :param db_host: pgSTAC database host (used only when *push* is ``True``).
    :param db_port: pgSTAC database port.
    :param db_name: pgSTAC database name.
    :param db_user: pgSTAC database user.
    :param db_password: pgSTAC database password.
    :param assets_base_url: HTTP base URL at which catalogue assets are served; used
        to rewrite ``file://`` hrefs when pushing to pgSTAC.
    """
    catalogue = MatchupCatalogue.open(catalogue_path)

    today = date or dt.date.today()
    dated_key = f"{key_prefix}:{today.isoformat()}"
    latest_key = f"{key_prefix}:latest"

    resolved_media_type = media_type or _detect_media_type(file_path)
    resolved_title = title or os.path.basename(file_path)

    asset = pystac.Asset(
        href=file_path,
        media_type=resolved_media_type,
        title=resolved_title,
    )

    ok = catalogue.add_asset_by_id(collection_id, item_id, dated_key, asset)
    if not ok:
        raise ValueError(
            f"Item {item_id!r} not found in collection {collection_id!r}. "
            "Check that the catalogue path and IDs are correct."
        )
    catalogue.add_asset_by_id(collection_id, item_id, latest_key, asset)

    log.info(
        "Registered %r and %r on item %s/%s",
        dated_key,
        latest_key,
        collection_id,
        item_id,
    )

    if push:
        _push_item(
            catalogue,
            collection_id,
            item_id,
            catalogue_path,
            config,
            db_host,
            db_port,
            db_name,
            db_user,
            db_password,
            assets_base_url,
        )


def _push_item(
    catalogue: MatchupCatalogue,
    collection_id: str,
    item_id: str,
    catalogue_path: str,
    config,
    db_host: Optional[str],
    db_port: Optional[int],
    db_name: Optional[str],
    db_user: Optional[str],
    db_password: Optional[str],
    assets_base_url: Optional[str],
) -> None:
    """Upsert a single updated item from *catalogue* into pgSTAC.

    :param catalogue: open :py:class:`~eomatch.mu_stac.MatchupCatalogue`.
    :param collection_id: collection containing the item.
    :param item_id: item to push.
    :param catalogue_path: root path of the catalogue on disk.
    :param config: eomatch config path or dict.
    :param db_host: pgSTAC host.
    :param db_port: pgSTAC port.
    :param db_name: pgSTAC database name.
    :param db_user: pgSTAC user.
    :param db_password: pgSTAC password.
    :param assets_base_url: HTTP base URL for rewriting asset hrefs.
    """
    try:
        from pypgstac.db import PgstacDB
        from pypgstac.load import Loader, Methods
    except ImportError:
        raise ImportError("pypgstac is required for --push. Install it with: pip install 'eomatch[ingest]'")

    from eomatch.ingest import _resolve_asset_hrefs, _rewrite_item_links

    col = catalogue.catalog.get_child(collection_id)
    if col is None:
        raise ValueError(f"Collection {collection_id!r} not found in catalogue")
    item = next(col.get_items(item_id), None)
    if item is None:
        raise ValueError(f"Item {item_id!r} not found in collection {collection_id!r}")
    _resolve_asset_hrefs(item, os.path.abspath(catalogue_path), assets_base_url)
    _rewrite_item_links(item)
    item_dict = item.to_dict()

    ctx = EOMatchContext(config) if config else EOMatchContext()
    ingest_cfg = ctx.get("ingest") or {}

    host = db_host or ingest_cfg.get("db_host", "localhost")
    port = int(db_port or ingest_cfg.get("db_port", 5432))
    name = db_name or ingest_cfg.get("db_name", "eomatch")
    user = db_user or ingest_cfg.get("db_user", "eomatch")
    password = db_password or ingest_cfg.get("db_password") or os.environ.get("PGPASSWORD", "")

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    log.info("Pushing item %s to pgSTAC at %s:%s/%s", item_id, host, port, name)

    with PgstacDB(dsn=dsn) as db:
        loader = Loader(db=db)
        loader.load_items(iter([item_dict]), insert_mode=Methods.upsert)

    log.info("Push complete for item %s", item_id)


def main() -> None:
    """CLI entry point for ``eomatch-add-asset``."""
    parser = argparse.ArgumentParser(
        description=(
            "Register an analysis output file as versioned STAC assets on a matchup item. "
            "Adds a dated key ({prefix}:YYYY-MM-DD) and a rolling {prefix}:latest key."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--catalogue",
        required=True,
        metavar="PATH",
        help="Path to the root catalogue directory or catalog.json",
    )
    parser.add_argument(
        "--collection-id",
        required=True,
        metavar="ID",
        help="STAC collection ID containing the target item",
    )
    parser.add_argument(
        "--item-id",
        required=True,
        metavar="ID",
        help="STAC item ID to attach the asset to",
    )
    parser.add_argument("--file", required=True, metavar="PATH", help="Path to the analysis output file")
    parser.add_argument(
        "--key-prefix",
        default="comparison",
        metavar="PREFIX",
        help="Asset key prefix (default: comparison)",
    )
    parser.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Date for the snapshot key (default: today)",
    )
    parser.add_argument(
        "--media-type",
        default=None,
        metavar="MIME",
        help="MIME type for the asset (auto-detected if not given)",
    )
    parser.add_argument(
        "--title",
        default=None,
        metavar="TEXT",
        help="Human-readable title for the asset (default: filename)",
    )
    parser.add_argument("--push", action="store_true", help="Also upsert the updated item into pgSTAC")
    parser.add_argument("--config", default=None, metavar="PATH", help="EOMatch YAML config file")
    parser.add_argument("--db-host", default=None)
    parser.add_argument("--db-port", type=int, default=None)
    parser.add_argument("--db-name", default=None)
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-password", default=None)
    parser.add_argument(
        "--assets-base-url",
        default=None,
        metavar="URL",
        help="HTTP base URL at which catalogue assets are served",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    date = dt.date.fromisoformat(args.date) if args.date else None

    register_analysis(
        catalogue_path=args.catalogue,
        collection_id=args.collection_id,
        item_id=args.item_id,
        file_path=args.file,
        key_prefix=args.key_prefix,
        date=date,
        media_type=args.media_type,
        title=args.title,
        push=args.push,
        config=args.config,
        db_host=args.db_host,
        db_port=args.db_port,
        db_name=args.db_name,
        db_user=args.db_user,
        db_password=args.db_password,
        assets_base_url=args.assets_base_url,
    )


if __name__ == "__main__":
    main()
