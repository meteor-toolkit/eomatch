"""eomatch.enrich.solar_elevation — solar elevation angle enricher.

Adds ``solar_elevation_deg``: the solar elevation angle (in degrees) at the
collocation region centroid at the midpoint of the combined product time
window.  Positive values indicate daytime; negative values indicate the sun
is below the horizon.

Requires ``pysolar`` (``pip install 'eomatch[enrich]'``).

Usage::

    from eomatch.enrich import enrich
    from eomatch.enrich.solar_elevation import solar_elevation

    enrich(catalogue, enrichers=[solar_elevation])

    # filter to daytime-only matchups:
    events = catalogue.get_events(
        properties={"solar_elevation_deg": {"gt": 0}}
    )
"""

import datetime as dt
from typing import Any, Dict

__all__ = ["solar_elevation"]


def solar_elevation(matchup) -> Dict[str, Any]:
    """Return the solar elevation angle at the collocation centroid midpoint.

    :param matchup: :py:class:`~eomatch.domain.Matchup` to enrich.
    :return: ``{"solar_elevation_deg": float}`` — positive is daytime.
    :raises ImportError: if ``pysolar`` is not installed.
    """
    try:
        from pysolar.solar import get_altitude
    except ImportError:
        raise ImportError(
            "pysolar is required for the solar_elevation enricher. Install it with: pip install 'eomatch[enrich]'"
        )

    region = matchup.collocation_region
    centroid = region.centroid
    start, stop = matchup.product_time_bounds
    midpoint = start + (stop - start) / 2
    if midpoint.tzinfo is None:
        midpoint = midpoint.replace(tzinfo=dt.timezone.utc)

    altitude = get_altitude(centroid.y, centroid.x, midpoint)
    return {"solar_elevation_deg": round(altitude, 2)}
