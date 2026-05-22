.. _analysis-assets:

##############################
Registering analysis results
##############################

After computing a comparison or validation result for a matchup, you can
attach the output file to the matchup's STAC item as a versioned asset.
This keeps the catalogue as the single source of truth: anyone querying
the central catalogue can see what analysis has been run on each matchup and
retrieve the result directly from the item metadata.

Two asset keys are written each time:

- ``{prefix}:YYYY-MM-DD`` — a dated snapshot that is never overwritten.
  Each run adds a new dated key alongside any previous ones.
- ``{prefix}:latest`` — always updated to point at the most recently registered
  file.  Useful when you only want the current result without having to know
  its date.

The default prefix is ``comparison``; you can supply any prefix to distinguish
different kinds of analysis (e.g. ``validation``, ``uncertainty``).

---

From the command line
######################

.. code-block:: bash

   eomatch-add-asset \
       --catalogue /data/my_catalogue \
       --collection-id LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A \
       --item-id     LC09_L1GT_089087_20220607_20220616_02_T2--S3A_EFR_20220607 \
       --file        /data/results/comparison_20260512.nc

This writes two assets to the item JSON on disk:

- ``comparison:2026-05-12`` (today's date by default)
- ``comparison:latest``

Override the date, prefix, or MIME type if needed:

.. code-block:: bash

   eomatch-add-asset \
       --catalogue /data/my_catalogue \
       --collection-id LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A \
       --item-id     LC09_L1GT_... \
       --file        /data/results/validation_run2.nc \
       --key-prefix  validation \
       --date        2026-05-01 \
       --media-type  application/x-netcdf \
       --title       "Validation run 2"

Add ``--push`` to also upsert the updated item directly into the running
pgSTAC database (requires the ``ingest`` extra and a reachable database):

.. code-block:: bash

   eomatch-add-asset \
       --catalogue /data/my_catalogue \
       --collection-id LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A \
       --item-id     LC09_L1GT_... \
       --file        /data/results/comparison_20260512.nc \
       --push \
       --db-host     your-server

Without ``--push``, run ``eomatch-ingest`` afterwards to synchronise the
whole catalogue (or just this item's collection) with pgSTAC.

---

From Python
############

.. code-block:: python

   import datetime as dt
   from eomatch.add_asset import register_analysis

   register_analysis(
       catalogue_path="/data/my_catalogue",
       collection_id="LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A",
       item_id="LC09_L1GT_089087_20220607_20220616_02_T2--S3A_EFR_20220607",
       file_path="/data/results/comparison_20260512.nc",
   )

Retrieve the item afterwards to confirm both keys were registered:

.. code-block:: python

   from eomatch.mu_stac import MatchupCatalogue

   cat = MatchupCatalogue.open("/data/my_catalogue")
   col = cat.catalog.get_child("LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A")
   item = next(col.get_items("LC09_L1GT_..."))

   print(item.assets.keys())
   # dict_keys(['comparison:2026-05-12', 'comparison:latest'])

   print(item.assets["comparison:latest"].href)
   # /data/results/comparison_20260512.nc

Multiple runs accumulate dated snapshots while ``latest`` rolls forward:

.. code-block:: python

   register_analysis(..., file_path="comparison_v1.nc", date=dt.date(2026, 5, 1))
   register_analysis(..., file_path="comparison_v2.nc", date=dt.date(2026, 5, 12))

   # item.assets now contains:
   # comparison:2026-05-01  →  comparison_v1.nc
   # comparison:2026-05-12  →  comparison_v2.nc
   # comparison:latest      →  comparison_v2.nc

Push to pgSTAC in the same call by passing ``push=True``:

.. code-block:: python

   register_analysis(
       catalogue_path="/data/my_catalogue",
       collection_id="LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A",
       item_id="LC09_L1GT_...",
       file_path="/data/results/comparison_20260512.nc",
       push=True,
       db_host="your-server",
       db_name="eomatch",
   )

Connection parameters fall back to the ``ingest`` section of your eomatch
config if not supplied explicitly:

.. code-block:: yaml

   # ~/.config/eomatch/user_config.yaml
   ingest:
     db_host: your-server
     db_name: eomatch
     db_user: postgres

Pass the password via the ``PGPASSWORD`` environment variable rather than
storing it in the config file:

.. code-block:: bash

   export PGPASSWORD=your-postgres-password

---

Media type detection
#####################

The MIME type is inferred from the file extension when ``media_type`` is not
given:

+-------------+------------------------------+
| Extension   | MIME type                    |
+=============+==============================+
| ``.nc``     | ``application/x-netcdf``     |
+-------------+------------------------------+
| ``.zarr``   | ``application/vnd.zarr``     |
+-------------+------------------------------+
| ``.tif``    | ``image/tiff``               |
+-------------+------------------------------+
| ``.tiff``   | ``image/tiff``               |
+-------------+------------------------------+
| ``.json``   | ``application/json``         |
+-------------+------------------------------+
| ``.csv``    | ``text/csv``                 |
+-------------+------------------------------+
| ``.png``    | ``image/png``                |
+-------------+------------------------------+
| ``.jpg``    | ``image/jpeg``               |
+-------------+------------------------------+
| other       | ``application/octet-stream`` |
+-------------+------------------------------+

---

How assets appear in the central catalogue
###########################################

Assets with ``file://`` hrefs (NFS paths) are visible on the internal API
(``/api/``) but are stripped from responses served by the external API
(``/external/``).  This means:

- Internal users (VPN access) see all assets, including analysis NetCDFs on
  NFS.
- External collaborators using the STAC Browser or ``eomatch-query`` see
  the matchup metadata but not the file paths.

To expose an analysis result to external users, serve it over HTTP and
register it with an ``http://`` href rather than a local path.

---

Full reference
###############

.. autofunction:: eomatch.add_asset.register_analysis
