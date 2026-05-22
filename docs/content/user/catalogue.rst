.. _catalogue:

#################
STAC catalogue
#################

EOMatch persists matchup events and matchup items to a
`STAC <https://stacspec.org>`_ catalogue on disk.  The catalogue is managed
through :py:class:`~eomatch.mu_stac.MatchupCatalogue` and follows this
structure:

.. code-block:: text

   catalogue/
   ├── catalog.json
   ├── {collection-1}/
   │   ├── collection.json
   │   └── YYYY/MM/DD/{item-id}.json                            # one per source product
   ├── {collection-2}/
   │   └── …
   ├── matchup-events-{col-1}-{platform-1}-vs-{col-2}-{platform-2}/
   │   ├── collection.json
   │   └── YYYY/MM/DD/{item-id}.json                            # one per MatchupEvent
   └── {col-1}-{platform-1}-vs-{col-2}-{platform-2}/
       ├── collection.json
       └── YYYY/MM/DD/{item-id}.json                            # one per Matchup

Items are organised by date rather than by per-item subdirectory, so a busy
collection stays flat and browsable.  Collection IDs include the platform name
for each sensor so that matchups between different satellite platforms within
the same collection are stored separately (e.g. ``LANDSAT_C2L1-Landsat-8``
vs ``LANDSAT_C2L1-Landsat-9``).  Pairs are sorted alphabetically by
collection name for stability, giving IDs such as
``LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A``.

Each matchup Item links back to its source products via ``derived_from`` links
and to its parent event via a ``related`` link (``matchup:role=event``).

Running the find-and-catalogue pipeline
########################################

The recommended way to populate the catalogue is via
:py:func:`~eomatch.find_and_catalogue.find_and_catalogue`, which runs the
:py:class:`~eomatch.finder.sat2sat.Sat2SatMUFinder` and saves everything in
one step:

.. code-block:: python

   from eomatch import EOMatchContext
   from eomatch.find_and_catalogue import find_and_catalogue

   ctx = EOMatchContext("my_config.yaml")
   catalogue = find_and_catalogue(context=ctx, path="/data/my_catalogue")

Or from the command line:

.. code-block:: bash

   eomatch-find --config my_config.yaml --path /data/my_catalogue

Add ``--verbose`` / ``-v`` for debug-level logging.

The catalogue path can also be set in the config file:

.. code-block:: yaml

   matchup_catalogue:
     path: /data/my_catalogue
     id: my-matchup-catalogue
     description: "Matchups for S2A vs S3A, June 2023"

Opening an existing catalogue
##############################

.. code-block:: python

   from eomatch.mu_stac import MatchupCatalogue

   cat = MatchupCatalogue.open("/data/my_catalogue/catalog.json")

Querying the catalogue
########################

Use :py:meth:`~eomatch.mu_stac.MatchupCatalogue.get_events` to retrieve
events and their matchups, with optional filtering:

.. code-block:: python

   import datetime as dt

   events = cat.get_events(
       collections=["S2_MSI_L1C", "S3_EFR"],
       start_time=dt.datetime(2023, 6, 1),
       stop_time=dt.datetime(2023, 6, 30),
       bbox=[-10.0, 40.0, 30.0, 70.0],
   )

   for event in events:
       print(event)
       for mu in event.matchup_set:
           print("  ", mu)

To restrict to events whose source products have already been downloaded:

.. code-block:: python

   events = cat.get_events(products_downloaded=True)

Downloading products
#####################

:py:meth:`~eomatch.mu_stac.MatchupCatalogue.download_products` downloads
all source products for a set of events and registers a ``"data"`` asset on
each product Item so that the download state is tracked in the catalogue:

.. code-block:: python

   cat.download_products(event_set=events)

Products that are already present on disk are registered without being
re-downloaded.  The updated Item JSON is written to disk after each product.

Managing products from the command line
########################################

The ``eomatch-download`` and ``eomatch-remove`` console scripts provide a
convenient way to bulk-download or remove source products without writing any
Python.  Both commands accept the same filtering flags:

.. code-block:: bash

   # Download all products for S2 vs Landsat matchups in June 2023
   eomatch-download \
       --path /data/my_catalogue \
       --collections S2_MSI_L1C,LANDSAT_C2L1 \
       --start-time 2023-06-01 \
       --stop-time 2023-06-30

   # Remove those products from disk (keeps catalogue metadata intact)
   eomatch-remove \
       --path /data/my_catalogue \
       --collections S2_MSI_L1C,LANDSAT_C2L1 \
       --start-time 2023-06-01 \
       --stop-time 2023-06-30

   # Remove asset references only, leave the files on disk
   eomatch-remove --path /data/my_catalogue --keep-files

Pass ``--verbose`` / ``-v`` for debug-level logging.  The catalogue path can be
omitted if ``matchup_catalogue.path`` is set in your config file; pass
``--config`` to load a non-default config.

Available filter flags (shared by both commands):

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Flag
     - Description
   * - ``--path PATH``
     - Catalogue root directory or ``catalog.json`` path.
   * - ``--collections C1,C2``
     - Comma-separated collection names (e.g. ``S2_MSI_L1C,LANDSAT_C2L1``).
   * - ``--platforms P1,P2``
     - Comma-separated platform names.
   * - ``--start-time DATETIME``
     - ISO 8601 start-time; events ending before this are excluded.
   * - ``--stop-time DATETIME``
     - ISO 8601 stop-time; events starting after this are excluded.
   * - ``--bbox LON_MIN,LAT_MIN,LON_MAX,LAT_MAX``
     - Spatial bounding-box filter.

``eomatch-remove`` additionally accepts ``--keep-files`` to remove the
``"data"`` asset from the catalogue without deleting the local files.

Managing products from Python
##############################

The same functionality is available as Python functions in
:py:mod:`eomatch.manage_products`:

.. code-block:: python

   import datetime as dt
   from eomatch import EOMatchContext
   from eomatch.manage_products import (
       download_catalogue_products,
       remove_catalogue_products,
   )

   ctx = EOMatchContext("my_config.yaml")

   # Download source products for matching events
   paths = download_catalogue_products(
       context=ctx,
       path="/data/my_catalogue",
       collections=["S2_MSI_L1C", "LANDSAT_C2L1"],
       start_time=dt.datetime(2023, 6, 1),
       stop_time=dt.datetime(2023, 6, 30),
   )
   print(f"Handled {len(paths)} product(s)")

   # Remove downloaded products from disk (and deregister from catalogue)
   n = remove_catalogue_products(
       context=ctx,
       path="/data/my_catalogue",
       collections=["S2_MSI_L1C", "LANDSAT_C2L1"],
       delete_files=True,  # set False to keep files, remove asset reference only
   )
   print(f"Removed {n} product asset(s)")

Both functions open the catalogue, apply the filters, and then act on every
matching event.  Products that appear in multiple matchups are processed only
once.  :py:func:`~eomatch.manage_products.download_catalogue_products`
registers a ``"data"`` STAC asset on each product Item after downloading so
that the catalogue tracks which products are present on disk.

Attaching assets
#################

You can attach arbitrary STAC assets to any Item or Collection in the
catalogue — useful for storing processing outputs alongside the raw products:

.. code-block:: python

   import pystac

   asset = pystac.Asset(href="/data/results/mu_stats.csv", media_type="text/csv")

   # Attach to a single matchup Item
   cat.add_matchup_asset(mu, asset_key="statistics", asset=asset)

   # Attach to a matchup event Item
   cat.add_event_asset(event, asset_key="thumbnail", asset=pystac.Asset(...))

   # Attach to the matchup Collection (sensor-pair level)
   cat.add_matchup_collection_asset(mu, asset_key="report", asset=pystac.Asset(...))

Corresponding ``remove_*`` methods are available for all three levels and will
optionally delete the local file from disk.
