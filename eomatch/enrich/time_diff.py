"""eomatch.enrich.time_diff — signed overpass time difference enricher.

Adds ``time_diff_s``: the signed difference in seconds between the start
times of the two sensor overpasses, computed as
``products[1].start_time - products[0].start_time`` (products are sorted
alphabetically by collection name).

Usage::

    from eomatch.enrich import enrich
    from eomatch.enrich.time_diff import time_diff

    enrich(catalogue, enrichers=[time_diff])

    # filterable:
    events = catalogue.get_events(properties={"time_diff_s": {"lt": 900}})
"""

from typing import Any, Dict

__all__ = ["time_diff"]


def time_diff(matchup) -> Dict[str, Any]:
    """Return the signed time difference between the two sensor overpasses.

    Uses ``products[1].start_time - products[0].start_time`` where products
    are sorted alphabetically by collection name, matching the order stored
    by :py:class:`~eomatch.domain.Matchup`.  The absolute value equals
    the ``matchup:time_diff_abs`` property already written by
    :py:meth:`~eomatch.domain.Matchup.to_stac_item`.

    :param matchup: :py:class:`~eomatch.domain.Matchup` to enrich.
    :return: ``{"time_diff_s": float}``
    """
    return {"time_diff_s": matchup.time_diff()}
