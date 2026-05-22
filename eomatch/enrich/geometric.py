"""eomatch.enrich.geometric — collocation region geometry enricher.

Adds three properties describing the collocation region shape:

- ``collocation_area_km2`` — area in km² (WGS-84 ellipsoid via ``pyproj``,
  falls back to degree² if pyproj is not installed).
- ``collocation_centroid_lon`` — longitude of the centroid in decimal degrees.
- ``collocation_centroid_lat`` — latitude of the centroid in decimal degrees.

Usage::

    from eomatch.enrich import enrich
    from eomatch.enrich.geometric import geometric

    enrich(catalogue, enrichers=[geometric])

    # filterable:
    events = catalogue.get_events(
        properties={"collocation_area_km2": {"gt": 1000}}
    )
"""

import logging
from typing import Any, Dict

__all__ = ["geometric"]

log = logging.getLogger(__name__)


def geometric(matchup) -> Dict[str, Any]:
    """Return the area and centroid of the collocation region.

    Area is computed on the WGS-84 ellipsoid via ``pyproj.Geod`` when
    available, falling back to planar degree² area if not installed.

    :param matchup: :py:class:`~eomatch.domain.Matchup` to enrich.
    :return: ``{"collocation_area_km2": float, "collocation_centroid_lon": float,
        "collocation_centroid_lat": float}``
    """
    region = matchup.collocation_region
    centroid = region.centroid

    try:
        from pyproj import Geod

        geod = Geod(ellps="WGS84")
        area_m2 = abs(geod.geometry_area_perimeter(region)[0])
        area_km2 = area_m2 / 1e6
    except ImportError:
        log.warning("pyproj not available — collocation_area_km2 is in degree², not km²")
        area_km2 = region.area

    return {
        "collocation_area_km2": round(area_km2, 3),
        "collocation_centroid_lon": round(centroid.x, 6),
        "collocation_centroid_lat": round(centroid.y, 6),
    }
