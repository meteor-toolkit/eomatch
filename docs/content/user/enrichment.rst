.. _enrichment:

##########################
Enriching matchup metadata
##########################

After a catalogue has been populated by
:py:func:`~eomatch.find_and_catalogue.find_and_catalogue`, each matchup
STAC Item carries a small set of core properties (time of overpass, bounding
box, sensor pair, …).  The enrichment system lets you compute *additional*
properties — area, time difference, solar elevation, land fraction, and
anything you define yourself — and write them back to the item JSON so they
persist in the catalogue and can be used to filter matchups.

Overview
########

An *enricher* is any callable with the signature::

    def my_enricher(matchup: Matchup) -> Dict[str, Any]: ...

It receives a :py:class:`~eomatch.domain.Matchup` and returns a plain
``dict`` of property names to values.
:py:func:`~eomatch.enrich.enrich` iterates all matchup items, reconstructs
the ``Matchup`` domain object for each, calls every enricher, and merges the
resulting dicts back into ``item.properties``.  If the item has a
``self_href`` the updated JSON is written to disk immediately so the properties
survive the process and can be ingested into the central catalogue.

Quick start
###########

.. code-block:: python

    from eomatch.mu_stac import MatchupCatalogue
    from eomatch.enrich import enrich
    from eomatch.enrich.time_diff import time_diff
    from eomatch.enrich.geometric import geometric
    from eomatch.enrich.solar_elevation import solar_elevation
    from eomatch.enrich.land_fraction import land_fraction

    catalogue = MatchupCatalogue.open("/data/my_catalogue")

    n = enrich(
        catalogue,
        enrichers=[time_diff, geometric, solar_elevation, land_fraction],
    )
    print(f"Enriched {n} matchup item(s).")

Or from the command line:

.. code-block:: bash

    eomatch-enrich \
        --catalogue /data/my_catalogue \
        --enricher eomatch.enrich.time_diff.time_diff \
        --enricher eomatch.enrich.geometric.geometric \
        --enricher eomatch.enrich.solar_elevation.solar_elevation \
        --enricher eomatch.enrich.land_fraction.land_fraction

Add ``--overwrite`` to replace properties that were written in an earlier run.
Add ``-v`` / ``--verbose`` for debug-level logging.

Built-in enrichers
##################

All built-in enrichers live as submodules of :py:mod:`eomatch.enrich`.
``solar_elevation`` and ``land_fraction`` require the optional ``enrich``
extra:

.. code-block:: bash

    pip install 'eomatch[enrich]'

.. list-table::
   :header-rows: 1
   :widths: 25 25 50

   * - Module
     - Property added
     - Notes
   * - :py:mod:`~eomatch.enrich.time_diff`
     - ``time_diff_s``
     - Signed seconds: ``products[1].start_time − products[0].start_time``.
   * - :py:mod:`~eomatch.enrich.geometric`
     - ``collocation_area_km2``, ``collocation_centroid_lon``,
       ``collocation_centroid_lat``
     - Area on the WGS-84 ellipsoid via ``pyproj``; falls back to degree² if
       ``pyproj`` is absent.
   * - :py:mod:`~eomatch.enrich.solar_elevation`
     - ``solar_elevation_deg``
     - Solar elevation at the collocation centroid midpoint.  Positive =
       daytime, negative = night-time.  Requires ``pysolar``.
   * - :py:mod:`~eomatch.enrich.land_fraction`
     - ``land_fraction``
     - Fraction of the collocation region over land (0.0 = ocean, 1.0 =
       land), computed from Natural Earth 110 m polygons.  Requires
       ``geopandas`` and ``geodatasets``.

Filtering by enriched properties
##################################

Once properties have been written to the catalogue, pass a ``properties``
filter to :py:meth:`~eomatch.mu_stac.MatchupCatalogue.get_events` to
restrict results to matchups that meet your criteria:

.. code-block:: python

    # Keep only matchups with an overpass time difference under 15 minutes
    events = catalogue.get_events(
        properties={"time_diff_s": {"lt": 900}}
    )

    # Daytime ocean matchups with a large overlap area
    events = catalogue.get_events(
        properties={
            "solar_elevation_deg": {"gt": 0},
            "land_fraction": {"lt": 0.05},
            "collocation_area_km2": {"gt": 5000},
        }
    )

Supported filter operators:

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Operator
     - Meaning
   * - ``lt``
     - property < threshold
   * - ``lte``
     - property ≤ threshold
   * - ``gt``
     - property > threshold
   * - ``gte``
     - property ≥ threshold
   * - ``eq``
     - property == value (also the default when the condition is a plain value)
   * - ``ne``
     - property != value
   * - ``in``
     - property is a member of a list

Writing a custom enricher
###########################

Any callable that accepts a :py:class:`~eomatch.domain.Matchup` and returns
a ``dict`` qualifies as an enricher.  To make it available on the CLI, place it
in an importable module and pass the dotted path:

.. code-block:: python

    # my_package/enrichers.py
    from typing import Any, Dict

    def cloud_cover(matchup) -> Dict[str, Any]:
        """Estimate cloud cover fraction from product metadata."""
        fractions = [
            getattr(p, "cloud_cover", None) for p in matchup.products
        ]
        valid = [f for f in fractions if f is not None]
        return {"cloud_cover_mean": sum(valid) / len(valid) if valid else None}

.. code-block:: bash

    eomatch-enrich \
        --catalogue /data/my_catalogue \
        --enricher my_package.enrichers.cloud_cover

Enrichers that raise an exception are logged as warnings and skipped for that
item — other enrichers in the same run are unaffected.

The ``overwrite`` flag
#######################

By default, :py:func:`~eomatch.enrich.enrich` skips keys that already exist
in ``item.properties``.  Pass ``overwrite=True`` (Python) or ``--overwrite``
(CLI) to replace existing values:

.. code-block:: python

    # Re-run after updating the land_fraction enricher
    enrich(catalogue, enrichers=[land_fraction], overwrite=True)

Ingesting enriched properties into the central catalogue
##########################################################

Enriched properties are written to the local ``item.properties`` dict and
persisted to the on-disk JSON immediately.  The next time you run
``eomatch-ingest`` the updated Items — including all new properties — are
pushed to the central pgSTAC catalogue, where they become queryable via the
`CQL2 filter extension <https://github.com/radiantearth/stac-api-spec/tree/main/fragments/filter>`_:

.. code-block:: bash

    # Local enrichment
    eomatch-enrich \
        --catalogue /data/my_catalogue \
        --enricher eomatch.enrich.time_diff.time_diff \
        --enricher eomatch.enrich.land_fraction.land_fraction

    # Push to central catalogue
    eomatch-ingest --catalogue /data/my_catalogue
