"""External STAC API filter proxy.

Forwards all requests to the internal stac-fastapi instance and:

1. Strips any asset whose href starts with ``file://`` from item and search
   responses, giving external users a clean view of the catalogue without
   exposing internal NFS paths.

2. Rewrites link hrefs in responses so that they point to the ``/external/``
   path prefix instead of the internal ``/api/`` prefix.  This ensures that
   STAC clients (including ``pystac_client``) follow links to the external
   endpoint rather than the write-protected internal one.

Configured via the environment variable ``UPSTREAM_URL`` (default:
``http://api-internal:8080``).
"""

import datetime as dt
import json
import os
import re
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

UPSTREAM = os.environ.get("UPSTREAM_URL", "http://api-internal:8080")
INTERNAL_PREFIX = "/api"
EXTERNAL_PREFIX = "/external"
STALE_THRESHOLD_HOURS = int(os.environ.get("STALE_THRESHOLD_HOURS", "48"))

app = FastAPI(title="EOMatch External STAC API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _rewrite_links(obj: Any, internal_base: str, external_base: str) -> Any:
    """Recursively replace *internal_base* with *external_base* in link hrefs.

    Handles both absolute URLs (``http://host/api/...``) and root-relative paths
    (``/api/...``) so that links stored without a hostname are also rewritten
    for external consumers.

    Only the ``href`` field of objects that also contain a ``rel`` field are
    rewritten (i.e. STAC link objects), so content inside item properties or
    asset descriptions is left untouched.

    :param obj: parsed JSON value to rewrite in place.
    :param internal_base: URL prefix to replace (e.g. ``http://host:8000/api``).
    :param external_base: URL prefix to substitute in (e.g. ``http://host:8000/external``).
    :return: the rewritten object (same reference for dicts/lists).
    """
    if isinstance(obj, dict):
        if "rel" in obj and "href" in obj:
            href = obj["href"]
            if isinstance(href, str):
                if href.startswith(internal_base):
                    obj["href"] = external_base + href[len(internal_base):]
                elif href.startswith(INTERNAL_PREFIX + "/") or href == INTERNAL_PREFIX:
                    obj["href"] = external_base + href[len(INTERNAL_PREFIX):]
        for v in obj.values():
            _rewrite_links(v, internal_base, external_base)
    elif isinstance(obj, list):
        for item in obj:
            _rewrite_links(item, internal_base, external_base)
    return obj


# Matches relative filesystem hrefs of the form:
#   (optional ../)*  COLLECTION_ID / YYYY / M / D / ITEM_ID .json
_RELATIVE_ITEM_HREF = re.compile(
    r"(?:\.\./)*([^/]+)/\d{4}/\d+/\d+/([^/]+)\.json$"
)


def _resolve_relative_item_href(href: str, api_base: str) -> Optional[str]:
    """Convert a relative filesystem STAC href to an absolute API URL.

    Parses the collection ID and item ID from the path structure used by the
    local eomatch catalogue and returns the canonical API item URL.  Returns
    ``None`` if the href does not match the expected pattern (e.g. it is already
    an absolute URL).

    :param href: the link href to inspect.
    :param api_base: absolute base URL of the STAC API endpoint to use
        (e.g. ``http://host:8000/external``).
    :return: rewritten absolute URL, or ``None`` if no rewrite is needed.
    """
    if not href or href.startswith("http://") or href.startswith("https://") or href.startswith("/"):
        return None
    m = _RELATIVE_ITEM_HREF.match(href)
    if not m:
        return None
    collection_id, item_id = m.group(1), m.group(2)
    return f"{api_base}/collections/{collection_id}/items/{item_id}"


def _filter_item(item: dict, api_base: str) -> dict:
    """Remove file:// assets and rewrite relative item links in a STAC item dict.

    :param item: STAC item dict to modify in place.
    :param api_base: absolute base URL used to construct rewritten link hrefs.
    :return: the modified item dict.
    """
    if "assets" in item:
        item["assets"] = {
            k: v
            for k, v in item["assets"].items()
            if not str(v.get("href", "")).startswith("file://")
        }
    for link in item.get("links", []):
        if link.get("rel") not in ("derived_from", "related"):
            continue
        rewritten = _resolve_relative_item_href(link.get("href", ""), api_base)
        if rewritten:
            link["href"] = rewritten
    return item


def _filter_response(data: dict, api_base: str) -> dict:
    """Strip file:// assets and rewrite relative item links in a STAC API response.

    :param data: parsed JSON response dict.
    :param api_base: absolute base URL used to construct rewritten link hrefs.
    :return: the modified response dict.
    """
    typ = data.get("type")
    if typ == "Feature":
        return _filter_item(data, api_base)
    if typ == "FeatureCollection":
        data["features"] = [_filter_item(f, api_base) for f in data.get("features", [])]
        return data
    return data


def _build_base(host: Optional[str], prefix: str) -> str:
    if host:
        scheme = "https" if not host.startswith("localhost") and ":" not in host.split(":")[0] else "http"
        return f"http://{host}{prefix}"
    return prefix


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness check — returns 200 OK when the proxy is running."""
    return JSONResponse({"status": "ok"})


@app.get("/health/catalogue")
async def health_catalogue() -> JSONResponse:
    """Catalogue freshness check.

    Queries the upstream STAC API for the most recent item across all
    collections and reports whether the catalogue has been updated recently.

    Returns HTTP 200 with ``status: "ok"`` or ``"stale"`` (newest item older
    than ``STALE_THRESHOLD_HOURS``), or HTTP 503 if the upstream is unreachable.

    The ``STALE_THRESHOLD_HOURS`` environment variable controls the threshold
    (default: 48 hours).
    """
    checked_at = dt.datetime.now(dt.timezone.utc).isoformat()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{UPSTREAM}/search",
                json={"limit": 1, "sortby": [{"field": "datetime", "direction": "desc"}]},
                headers={"Content-Type": "application/json"},
            )
        data = resp.json()
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "detail": str(exc), "checked_at": checked_at},
            status_code=503,
        )

    features = data.get("features", [])
    context = data.get("context", {})
    total_items = context.get("matched")

    newest_datetime: Optional[str] = None
    hours_since: Optional[float] = None

    if features:
        newest_datetime = features[0].get("properties", {}).get("datetime")
        if newest_datetime:
            try:
                newest_dt = dt.datetime.fromisoformat(newest_datetime.rstrip("Z"))
                hours_since = (dt.datetime.now(dt.timezone.utc) - newest_dt.replace(tzinfo=dt.timezone.utc)).total_seconds() / 3600
            except ValueError:
                pass

    if hours_since is None:
        catalogue_status = "unknown"
    elif hours_since > STALE_THRESHOLD_HOURS:
        catalogue_status = "stale"
    else:
        catalogue_status = "ok"

    return JSONResponse({
        "status": catalogue_status,
        "checked_at": checked_at,
        "newest_item_datetime": newest_datetime,
        "hours_since_newest_item": round(hours_since, 1) if hours_since is not None else None,
        "stale_threshold_hours": STALE_THRESHOLD_HOURS,
        "total_items": total_items,
    })


@app.api_route("/{path:path}", methods=["GET", "HEAD", "OPTIONS", "POST"])
async def proxy(request: Request, path: str) -> Response:
    """Proxy a request to the internal API, filtering assets and rewriting links."""
    url = f"{UPSTREAM}/{path}"
    params = dict(request.query_params)
    body = await request.body()

    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "accept-encoding")
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.request(
            method=request.method,
            url=url,
            params=params,
            content=body,
            headers=forward_headers,
        )

    content_type = resp.headers.get("content-type", "")
    if "json" in content_type:
        try:
            data = resp.json()
            host = request.headers.get("host") or request.headers.get("x-forwarded-host")
            internal_base = _build_base(host, INTERNAL_PREFIX)
            external_base = _build_base(host, EXTERNAL_PREFIX)

            data = _filter_response(data, external_base)

            # Rewrite link hrefs: /api/ → /external/ so that STAC clients
            # follow links to this proxy rather than the protected internal API.
            _rewrite_links(data, internal_base, external_base)

            return JSONResponse(content=data, status_code=resp.status_code)
        except (json.JSONDecodeError, ValueError):
            pass

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
    )
