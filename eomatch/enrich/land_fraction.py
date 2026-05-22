"""eomatch.enrich.land_fraction — land/ocean fraction enricher.

Adds ``land_fraction``: the fraction of the collocation region that lies
over land, as a value between 0.0 (entirely ocean) and 1.0 (entirely land).

Uses Natural Earth low-resolution land polygons bundled with ``geopandas``
(or via ``geodatasets`` on newer installations).  The land geometry is loaded
and cached the first time the enricher is called.

Requires ``geopandas`` (``pip install 'eomatch[enrich]'``).

Usage::

    from eomatch.enrich import enrich
    from eomatch.enrich.land_fraction import land_fraction

    enrich(catalogue, enrichers=[land_fraction])

    # filter to ocean-only matchups:
    events = catalogue.get_events(
        properties={"land_fraction": {"lt": 0.05}}
    )
"""

from typing import Any, Dict

__all__ = ["land_fraction"]

_land_geometry = None


def _get_land_geometry():
    global _land_geometry
    if _land_geometry is not None:
        return _land_geometry
    from eomatch.deps import lazy_geopandas

    gpd = lazy_geopandas()
    # geopandas < 1.0 ships naturalearth_lowres via gpd.datasets;
    # newer versions delegate to the geodatasets package.
    try:
        path = gpd.datasets.get_path("naturalearth_lowres")
        world = gpd.read_file(path)
    except AttributeError:
        try:
            import geodatasets
        except ImportError:
            raise ImportError("Could not load Natural Earth data. Install geodatasets: pip install geodatasets")
        world = gpd.read_file(geodatasets.get_path("naturalearth.land"))
    union = world.geometry.union_all() if hasattr(world.geometry, "union_all") else world.geometry.unary_union
    _land_geometry = union
    return _land_geometry


def land_fraction(matchup) -> Dict[str, Any]:
    """Return the fraction of the collocation region that lies over land.

    :param matchup: :py:class:`~eomatch.domain.Matchup` to enrich.
    :return: ``{"land_fraction": float}`` — 0.0 is entirely ocean, 1.0 entirely land.
    :raises ImportError: if ``geopandas`` is not installed.
    """
    land = _get_land_geometry()
    region = matchup.collocation_region
    total_area = region.area
    if total_area == 0:
        return {"land_fraction": 0.0}
    land_area = region.intersection(land).area
    return {"land_fraction": round(land_area / total_area, 4)}
