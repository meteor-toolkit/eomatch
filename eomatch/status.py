"""eomatch.status — report catalogue item counts and freshness."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import urllib.error
import urllib.request
from typing import Any, List, Optional, Tuple

from eomatch import EOMatchContext

__all__ = ["status"]

log = logging.getLogger(__name__)


def _get(url: str) -> Any:
    """HTTP GET and parse JSON response.

    :param url: URL to fetch.
    :return: parsed JSON value.
    :raises urllib.error.URLError: on network or HTTP error.
    """
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())


def _post(url: str, payload: dict) -> Any:
    """HTTP POST with a JSON body and parse JSON response.

    :param url: URL to post to.
    :param payload: dict to serialise as the request body.
    :return: parsed JSON value.
    :raises urllib.error.URLError: on network or HTTP error.
    """
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _collection_stats(api_url: str, collection_id: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Return (count, newest_datetime, oldest_datetime) for one collection.

    Uses the STAC API search endpoint.  ``count`` is read from the context
    extension (``context.matched``) when available, otherwise ``None``.

    :param api_url: base URL of the STAC API (no trailing slash).
    :param collection_id: collection to query.
    :return: tuple of (count, newest ISO datetime string, oldest ISO datetime string).
    """
    search_url = f"{api_url}/search"
    base = {"collections": [collection_id], "limit": 1}

    count: Optional[int] = None
    newest: Optional[str] = None
    oldest: Optional[str] = None

    try:
        resp = _post(search_url, {**base, "sortby": [{"field": "datetime", "direction": "desc"}]})
        features = resp.get("features", [])
        if features:
            newest = features[0].get("properties", {}).get("datetime")
        count = resp.get("context", {}).get("matched")
    except Exception as exc:
        log.debug("Failed to fetch newest for %s: %s", collection_id, exc)

    try:
        resp = _post(search_url, {**base, "sortby": [{"field": "datetime", "direction": "asc"}]})
        features = resp.get("features", [])
        if features:
            oldest = features[0].get("properties", {}).get("datetime")
    except Exception as exc:
        log.debug("Failed to fetch oldest for %s: %s", collection_id, exc)

    return count, newest, oldest


def status(api_url: str, config=None) -> None:
    """Print a status summary of the central catalogue to stdout.

    Connects to the STAC API at *api_url* and reports item counts and date
    ranges for every collection.  Works against both the internal (``/api/``)
    and external (``/external/``) endpoints.

    Item counts are read from the ``context`` extension in pgSTAC search
    responses and shown as ``?`` when unavailable.

    Example::

        from eomatch.status import status

        status("http://your-server:8000/api/")

    :param api_url: base URL of the STAC API (e.g. ``http://server:8000/api/``).
    :param config: path to a eomatch YAML config file, or a dict of
        overrides.  If ``None``, the package defaults are used.  The
        ``query.api_url`` config key is used when *api_url* is not given.
    """
    ctx = EOMatchContext(config) if config else EOMatchContext()
    _url = api_url or (ctx.get("query") or {}).get("api_url")
    if not _url:
        raise ValueError("No API URL supplied. Pass api_url= or set query.api_url in config.")
    _url = _url.rstrip("/")

    checked_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    try:
        resp = _get(f"{_url}/collections")
    except urllib.error.URLError as exc:
        print(f"ERROR: could not reach API at {_url}: {exc}")
        return

    collections = resp.get("collections", [])
    if not collections:
        print(f"No collections found at {_url}.")
        return

    rows: List[Tuple[str, Optional[int], Optional[str], Optional[str]]] = []
    for col in collections:
        col_id = col["id"]
        count, newest, oldest = _collection_stats(_url, col_id)
        rows.append((col_id, count, newest, oldest))

    id_w = max(len(r[0]) for r in rows)
    id_w = max(id_w, 12)

    print()
    print("EOMatch Catalogue Status")
    print(f"API:     {_url}")
    print(f"Checked: {checked_at}")
    print()
    header = f"{'Collection':<{id_w}}  {'Items':>8}  {'Newest':^12}  {'Oldest':^12}"
    print(header)
    print("-" * len(header))
    for col_id, count, newest, oldest in rows:
        count_str = f"{count:,}" if count is not None else "?"
        newest_str = newest[:10] if newest else "?"
        oldest_str = oldest[:10] if oldest else "?"
        print(f"{col_id:<{id_w}}  {count_str:>8}  {newest_str:^12}  {oldest_str:^12}")
    print()


def main() -> None:
    """CLI entry point for ``eomatch-status``."""
    parser = argparse.ArgumentParser(
        description="Print item counts and date ranges for every collection in the catalogue.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--api-url",
        default=None,
        metavar="URL",
        help=("Base URL of the STAC API (e.g. http://server:8000/api/). Falls back to query.api_url in config."),
    )
    parser.add_argument("--config", default=None, metavar="PATH", help="EOMatch YAML config file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    status(api_url=args.api_url, config=args.config)


if __name__ == "__main__":
    main()
