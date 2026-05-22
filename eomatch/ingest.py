"""eomatch.ingest — push a local pystac catalogue into a pgSTAC database."""

import argparse
import logging
import os
from typing import Iterator, Optional

import pystac

from eomatch import EOMatchContext

__all__ = ["ingest"]

log = logging.getLogger(__name__)


def _iter_collections(catalog: pystac.Catalog) -> Iterator[dict]:
    """Yield STAC collection dicts from *catalog*, depth-first.

    :param catalog: root pystac catalogue or collection to walk.
    :return: iterator of collection dicts in depth-first order.
    """
    for child in catalog.get_children():
        if isinstance(child, pystac.Collection):
            yield child.to_dict()
            yield from _iter_collections(child)


def _resolve_asset_hrefs(item: pystac.Item, catalogue_path: str, assets_base_url: Optional[str]) -> None:
    """Convert relative asset hrefs to absolute, optionally remapping to HTTP URLs.

    Relative hrefs are resolved against the item's self href (giving absolute
    ``file://`` paths).  If *assets_base_url* is supplied, any href that falls
    under *catalogue_path* on disk is rewritten as an HTTP URL so the STAC
    Browser can fetch it.

    :param item: pystac item to modify in-place.
    :param catalogue_path: absolute path to the root of the local catalogue.
    :param assets_base_url: HTTP base URL at which *catalogue_path* is served
        (e.g. ``http://localhost:8000/catalogue``).  If ``None``, hrefs are
        left as ``file://`` paths.
    """
    if not item.assets:
        return
    item.make_asset_hrefs_absolute()
    if not assets_base_url:
        return
    root = os.path.abspath(catalogue_path)
    base = assets_base_url.rstrip("/")
    for asset in item.assets.values():
        href = asset.href
        # Normalise file:// → plain path
        if href.startswith("file://"):
            href = href[7:]
        href = os.path.abspath(href)
        if href.startswith(root):
            rel = href[len(root) :].lstrip("/")
            if not os.path.exists(href):
                log.warning("Asset file not found on disk: %s", href)
            asset.href = f"{base}/{rel}"


def _rewrite_item_links(item: pystac.Item) -> None:
    """Rewrite ``derived_from`` and ``related`` links to root-relative API paths.

    stac-fastapi resolves any relative hrefs stored in pgSTAC against the
    request URL, which produces wrong absolute URLs (the API path structure
    does not mirror the catalogue directory tree).  This rewrites those links
    to root-relative API paths (``/api/collections/{id}/items/{id}``) before
    ingest so that stac-fastapi resolves them correctly to
    ``http://<host>/api/collections/{id}/items/{id}``.

    The local catalogue JSON files are never modified — only the in-memory
    item passed to pypgstac is changed.  Links that cannot be resolved to a
    pystac Item (e.g. already-absolute HTTP hrefs or already root-relative
    paths) are left untouched.

    :param item: pystac item to modify in-place.
    """
    for link in item.links:
        if link.rel not in ("derived_from", "related"):
            continue
        href = link.href if isinstance(link.href, str) else ""
        if href.startswith("http://") or href.startswith("https://") or href.startswith("/"):
            continue
        try:
            if isinstance(link.target, pystac.Item):
                target = link.target
            else:
                abs_href = link.get_absolute_href()
                if not abs_href:
                    continue
                target = pystac.Item.from_file(abs_href)
        except Exception:
            continue
        collection_id = target.collection_id or ""
        if not collection_id:
            continue
        link.target = f"/api/collections/{collection_id}/items/{target.id}"


def _iter_items(
    catalog: pystac.Catalog,
    catalogue_path: str,
    assets_base_url: Optional[str],
) -> Iterator[dict]:
    """Yield every STAC item dict reachable from *catalog*.

    Asset hrefs are resolved to absolute paths before serialisation so that
    relative hrefs stored in the pystac files do not end up in pgSTAC as
    unresolvable relative strings.  Item-to-item links (``derived_from``,
    ``related``) are rewritten to root-relative API paths so that stac-fastapi
    resolves them to correct absolute URLs rather than mangling the relative
    filesystem paths.

    :param catalog: root pystac catalogue or collection to walk.
    :param catalogue_path: absolute path to the root of the local catalogue,
        used to anchor relative asset hrefs.
    :param assets_base_url: if set, rewrite ``file://`` asset hrefs to HTTP
        URLs rooted at this URL (see :func:`_resolve_asset_hrefs`).
    :return: iterator of item dicts with resolved asset hrefs.
    """
    for item in catalog.get_items(recursive=True):
        _resolve_asset_hrefs(item, catalogue_path, assets_base_url)
        _rewrite_item_links(item)
        yield item.to_dict()


def ingest(
    catalogue_path: Optional[str] = None,
    config=None,
    db_host: Optional[str] = None,
    db_port: Optional[int] = None,
    db_name: Optional[str] = None,
    db_user: Optional[str] = None,
    db_password: Optional[str] = None,
    assets_base_url: Optional[str] = None,
) -> None:
    """Push a local pystac catalogue into a pgSTAC database.

    Reads every collection and item from the local catalogue and loads them
    into pgSTAC using upsert semantics, so re-running after a partial failure
    or incremental update is always safe.

    Asset hrefs that are stored as relative paths in the local catalogue are
    resolved to absolute ``file://`` paths before ingest.  If *assets_base_url*
    is supplied, hrefs are further rewritten to HTTP URLs so the STAC Browser
    can load thumbnails.  This requires the catalogue asset files to be served
    over HTTP at that URL (e.g. via the ``/catalogue/`` nginx location in the
    Docker Compose stack).

    ``derived_from`` and ``related`` item links are rewritten to root-relative
    API paths (``/api/collections/{id}/items/{id}``) before ingest.
    stac-fastapi resolves these to correct absolute URLs at serve time;
    the filter-proxy then rewrites them to ``/external/`` paths for external
    consumers.  The local catalogue JSON files are never modified.

    Connection parameters are resolved in priority order: explicit keyword
    argument → ``ingest`` section of the eomatch config → environment
    variable ``PGPASSWORD`` (password only).

    Requires the ``pypgstac`` package (``pip install pypgstac`` or
    ``pip install eomatch[ingest]``).

    Example usage::

        from eomatch.ingest import ingest

        ingest(
            catalogue_path="/data/my_catalogue",
            assets_base_url="http://my-server:8000/catalogue",
            db_host="localhost",
            db_name="eomatch",
            db_user="postgres",
            db_password="secret",
        )

    :param catalogue_path: path to the root ``catalog.json``.  Defaults to
        ``matchup_catalogue.path`` from the eomatch config.
    :param config: path to a eomatch YAML config file, or a dict of
        overrides.  If ``None``, the package and user configs are used.
    :param db_host: pgSTAC database host.
    :param db_port: pgSTAC database port.
    :param db_name: pgSTAC database name.
    :param db_user: pgSTAC database user.
    :param db_password: pgSTAC database password.  Falls back to the
        ``PGPASSWORD`` environment variable if not supplied.
    :param assets_base_url: HTTP base URL at which the catalogue asset files
        are served.  When set, asset hrefs are rewritten from local ``file://``
        paths to HTTP URLs so the STAC Browser can load thumbnails.
    """
    try:
        from pypgstac.db import PgstacDB
        from pypgstac.load import Loader, Methods
    except ImportError:
        raise ImportError("pypgstac is required for ingest. Install it with: pip install 'eomatch[ingest]'")

    ctx = EOMatchContext(config) if config else EOMatchContext()
    ingest_cfg = ctx.get("ingest") or {}

    catalogue_cfg = ctx.get("matchup_catalogue") or {}
    path = catalogue_path or catalogue_cfg.get("path")
    if not path:
        raise ValueError("No catalogue path supplied. Pass catalogue_path= or set matchup_catalogue.path in config.")

    catalog_file = os.path.join(path, "catalog.json")
    log.info("Opening catalogue: %s", catalog_file)
    catalog = pystac.Catalog.from_file(catalog_file)

    host = db_host or ingest_cfg.get("db_host", "localhost")
    port = int(db_port or ingest_cfg.get("db_port", 5432))
    name = db_name or ingest_cfg.get("db_name", "eomatch")
    user = db_user or ingest_cfg.get("db_user", "eomatch")
    password = db_password or ingest_cfg.get("db_password") or os.environ.get("PGPASSWORD", "")

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    log.info("Connecting to pgSTAC at %s:%s/%s", host, port, name)

    with PgstacDB(dsn=dsn) as db:
        loader = Loader(db=db)

        collections = list(_iter_collections(catalog))
        if collections:
            log.info("Loading %d collection(s)", len(collections))
            loader.load_collections(iter(collections), insert_mode=Methods.upsert)

        items = list(_iter_items(catalog, path, assets_base_url))
        log.info("Loading %d item(s)", len(items))
        loader.load_items(iter(items), insert_mode=Methods.upsert)

    log.info("Ingest complete — %d collection(s), %d item(s)", len(collections), len(items))


def main() -> None:
    """CLI entry point for ``eomatch-ingest``."""
    parser = argparse.ArgumentParser(
        description="Push a local eomatch pystac catalogue into a pgSTAC database.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", metavar="PATH", help="EOMatch YAML config file")
    parser.add_argument(
        "--catalogue",
        metavar="PATH",
        help="Path to local catalogue root (overrides matchup_catalogue.path from config)",
    )
    parser.add_argument("--db-host", default=None, help="pgSTAC database host")
    parser.add_argument("--db-port", type=int, default=None, help="pgSTAC database port")
    parser.add_argument("--db-name", default=None, help="pgSTAC database name")
    parser.add_argument("--db-user", default=None, help="pgSTAC database user")
    parser.add_argument(
        "--db-password",
        default=None,
        help="pgSTAC database password (falls back to PGPASSWORD env var)",
    )
    parser.add_argument(
        "--assets-base-url",
        default=None,
        metavar="URL",
        help=(
            "HTTP base URL at which the catalogue asset files are served. "
            "When set, relative asset hrefs (e.g. thumbnails) are rewritten "
            "to HTTP URLs so the STAC Browser can load them. "
            "Example: http://localhost:8000/catalogue"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ingest(
        catalogue_path=args.catalogue,
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
