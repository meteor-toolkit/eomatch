.. _central-catalogue:

####################
Central catalogue
####################

EOMatch includes a server-side catalogue stack that lets the whole team
share a single searchable database of matchup events, matchup items, and
analysis results.  Researchers can query the central catalogue to pull a
subset of items into a local working catalogue, and the pipeline can push
new results back in.

Two HTTP endpoints are served:

- **Internal** (``/api/``) — full assets, including ``file://`` paths to NFS
  products and analysis files.  Write access is protected by an API key.
  Accessible over the VPN only.
- **External** (``/external/``) — ``file://`` assets are stripped before
  responses leave the server.  Read-only.  Suitable for sharing with
  collaborators outside NPL.

See :doc:`../../design/api_architecture` for the full stack design and
:doc:`../../design/deployment_guide` for server setup instructions.

---

Querying the central catalogue
################################

Install the query extra alongside eomatch:

.. code-block:: bash

   pip install -e '.[query]'

This installs ``pystac_client``, the library used to search the STAC API.

From the command line
----------------------

.. code-block:: bash

   eomatch-query \
       --api-url http://your-server:8000/external/ \
       --output ./my_matchups

Filter by collection, time range, or bounding box:

.. code-block:: bash

   eomatch-query \
       --api-url http://your-server:8000/external/ \
       --output ./my_matchups \
       --collections LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A \
       --start-time 2022-01-01 \
       --end-time 2022-12-31 \
       --bbox -10 40 30 70

Add ``-v`` / ``--verbose`` for debug-level logging.

Queries are **idempotent** — re-running after the central catalogue has been
updated adds new items and replaces any that have changed locally.

From Python
-----------

.. code-block:: python

   import datetime as dt
   from eomatch.query import query

   query(
       api_url="http://your-server:8000/external/",
       output_path="./my_matchups",
       collections=["LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A"],
       start_time=dt.datetime(2022, 1, 1),
       end_time=dt.datetime(2022, 12, 31),
   )

``query()`` returns the :py:class:`pystac.Catalog` that was saved, which
you can pass directly to :py:class:`~eomatch.mu_stac.MatchupCatalogue`.

Items referenced via ``related`` or ``derived_from`` links (matchup items
and source product items) are fetched automatically even if they are not
in the requested collections, so that
:py:meth:`~eomatch.mu_stac.MatchupCatalogue.get_events` works on the
result without any further network access.

Full reference:

.. autofunction:: eomatch.query.query

---

Working with the result
########################

The output directory is a valid local pystac catalogue in the same format
that ``eomatch-find`` produces.  Open it with
:py:class:`~eomatch.mu_stac.MatchupCatalogue`:

.. code-block:: python

   from eomatch.mu_stac import MatchupCatalogue

   cat = MatchupCatalogue.open("./my_matchups/catalog.json")

   events = cat.get_events(
       start_time=dt.datetime(2022, 6, 1),
       stop_time=dt.datetime(2022, 6, 30),
   )

   for event in events:
       for mu in event.matchup_set:
           ds = mu.return_matchup_dataset()   # reads products from NFS
           # analyse...

If you are working outside NPL without access to the NFS, download the
source products first:

.. code-block:: bash

   # Pull items from the external API (no file:// assets)
   eomatch-query \
       --api-url http://your-server:8000/external/ \
       --output ./my_matchups

   # Download the EO products from the public archives (CEDA, AWS, …)
   eomatch-download --path ./my_matchups

---

Checking catalogue status
###########################

``eomatch-status`` prints a summary of item counts and date ranges for every
collection currently in the central catalogue:

.. code-block:: bash

   eomatch-status --api-url http://your-server:8000/api/

Connection can also be read from your user config:

.. code-block:: yaml

   # ~/.config/eomatch/user_config.yaml
   query:
     api_url: http://your-server:8000/api/

Then simply run:

.. code-block:: bash

   eomatch-status

---

Pushing to the central catalogue
##################################

After running ``eomatch-find`` locally, push the results to the central
catalogue with ``eomatch-ingest``:

.. code-block:: bash

   pip install -e '.[ingest]'

   eomatch-ingest \
       --catalogue /data/my_catalogue \
       --db-host your-server \
       --db-user postgres \
       --assets-base-url http://your-server:8000/catalogue

``--assets-base-url`` rewrites relative asset hrefs (such as thumbnail
``file://`` paths) to HTTP URLs served statically by the proxy, so the STAC
Browser can load them.  Omit it if your items have no local-file assets.

Connection parameters can also be set in your user config so you do not
have to pass them every time:

.. code-block:: yaml

   # ~/.config/eomatch/user_config.yaml
   ingest:
     db_host: your-server
     db_port: 5432
     db_name: eomatch
     db_user: postgres

Pass the password via the ``PGPASSWORD`` environment variable to avoid
storing credentials in a config file:

.. code-block:: bash

   export PGPASSWORD=your-postgres-password
   eomatch-ingest --config my_run.yaml

Ingest uses upsert semantics, so re-running after a partial failure or an
incremental update is always safe.

See :doc:`../../design/deployment_guide` for instructions on setting up the
server-side stack.

---

How links work across the stack
##################################

EOMatch uses STAC ``derived_from`` and ``related`` links to connect matchup
items to their parent events and source product items.  These links take
different forms depending on where they live:

**Local catalogue (single source of truth)**
    Items store relative filesystem paths between each other, e.g.
    ``../../../../LANDSAT_C2L1/2022/5/21/LC09_...json``.  These are resolved
    directly by pystac when you open a local catalogue, and are what
    :py:class:`~eomatch.mu_stac.MatchupCatalogue` and
    :py:meth:`~eomatch.domain.Matchup.return_matchup_dataset` rely on.
    The local JSON files are **never** modified by the ingest process.

**pgSTAC / internal API (``/api/``)**
    During ingest, ``_rewrite_item_links`` converts the relative filesystem
    paths to root-relative API paths (``/api/collections/{id}/items/{id}``)
    in memory before the items are written to the database.  stac-fastapi
    then resolves these against the request host when serving items, producing
    correct absolute URLs such as
    ``http://your-server:8000/api/collections/LANDSAT_C2L1/items/LC09_...``.

**Filter-proxy / external API (``/external/``)**
    The filter-proxy rewrites ``/api/`` link hrefs to ``/external/`` hrefs
    on the fly so that STAC Browser navigation stays on the external endpoint.
    This is what makes "Additional Resources" links in STAC Browser work.

**After ``eomatch-query``**
    Items downloaded from the API carry absolute HTTP links.
    ``_rewrite_cross_item_links`` converts them back to relative filesystem
    paths before saving the local catalogue, so the result works identically
    to one produced by ``eomatch-find``.
