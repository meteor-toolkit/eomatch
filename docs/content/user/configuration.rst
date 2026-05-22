.. _configuration:

#############
Configuration
#############

EOMatch reads all runtime parameters from YAML configuration files.  The
system uses three layers, each merged on top of the previous:

.. code-block:: text

   package defaults          (eomatch/etc/default_config.yaml — do not edit)
        ↓
   user config               (~/.config/eomatch/user_config.yaml)
        ↓
   per-run override          (passed via --config on any CLI command)

You only need to supply the keys you want to override — everything else falls
back to the package defaults.

Initialising the user config
#############################

Run ``eomatch-init`` once after installation to create your user config:

.. code-block:: bash

   eomatch-init

This writes a fully-commented template to
``~/.config/eomatch/user_config.yaml``.  Running it again is safe — it will
not overwrite an existing file unless you delete it first.

EOMatch also initialises the config automatically on first import, so the
file will exist even if you never call ``eomatch-init`` explicitly.

Config file sections
####################

STAC catalogue (``matchup_catalogue``)
=======================================

Controls where eomatch stores and reads its catalogue.  Used by every CLI
command and by :py:class:`~eomatch.mu_stac.MatchupCatalogue` directly.

.. code-block:: yaml

   matchup_catalogue:
     path: /data/my_catalogue   # root directory for the catalogue on disk
     id: matchup-catalogue      # STAC catalogue ID
     description: Matchup catalogue

``path`` can be omitted from the user config and passed at run time instead
(``--path`` on the CLI, or as a constructor argument in Python).

Satellite finder settings
==========================

These flat keys are used by :py:class:`~eomatch.finder.sat2sat.Sat2SatMUFinder`
and the ``eomatch-find`` command.  They are most naturally placed in a
per-run ``--config`` file alongside ``matchup_catalogue.path``, though you can
set defaults for platforms and collections in your user config if you always
work with the same sensor pair.

.. code-block:: yaml

   # Which satellites and collections to match — order must correspond.
   platforms: Sentinel-2A, Landsat-9
   collections: S2_MSI_L1C, LANDSAT_C2L1

   # Search time window (format: "YYYY-MM-DD HH:MM:SS").
   start_time: "2023-01-01 00:00:00"
   end_time:   "2023-12-31 23:59:59"

   # Spatial filter — omit or leave blank to search globally.
   min_lat: 45.0
   max_lat: 55.0
   min_lon: -5.0
   max_lon: 10.0

Orbit crossover detection is handled by ``orbitx``.  The NetCDF path is
resolved in the following priority order:

**Option A — per-combo NetCDF files** (recommended when working with multiple
satellite pairs).  Keys use the platform-aware combo ID format produced by
:py:func:`~eomatch.domain._matchup_collection_id`:

.. code-block:: yaml

   orbitx_netcdf_files:
     LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A: /path/to/LS9_S2A.nc
     LANDSAT_C2L1-Landsat-8-vs-S2_MSI_L1C-S2B: /path/to/LS8_S2B.nc

**Option B — single pre-computed NetCDF** (flat fallback; used when no
per-combo entry is found in ``orbitx_netcdf_files``):

.. code-block:: yaml

   orbitx_netcdf_path: /path/to/crossovers.nc

**Option C — run orbitx from scratch** (used when neither A nor B is set):

.. code-block:: yaml

   propagation_sampling_interval: 30     # satellite position step (seconds)
   interpolation_sampling_interval: 1    # crossover refinement step (seconds)
   space_diff_threshold: 100.0           # max cross-track distance (km)
   time_diff_threshold: 1800             # max time difference (seconds)
   check_before: false
   check_after: false
   has_land_ocean_mask: false
   custom_satellites:                    # blank for standard TLEs
   dump_orbit: false

Scientific dataset reading (``read``)
======================================

Controls how :py:class:`~eomatch.datatree.BuildMUDT` reads products via
``eoio``.  The package defaults request no bands (``meas: []``) so you must
configure this section to get any data out of
:py:meth:`~eomatch.domain.Matchup.return_matchup_dataset`.

.. code-block:: yaml

   read:
     defaults:
       vars_sel:
         meas: []       # band selection — list of band IDs, or "rgb" sentinel
         aux: []        # auxiliary variables
       read_params:
         use_chunks: false
         metadata_level: true
         save_extracted: false
       processors: {}

     # Per-collection overrides — merged on top of defaults above.
     collections:
       LANDSAT_C2L1:
         vars_sel:
           meas: [B2, B3, B4, B5]
       S2_MSI_L1C:
         vars_sel:
           meas: [B02, B03, B04, B8A]

``vars_sel`` and ``processors`` are replaced wholesale at each level;
``read_params`` keys are merged individually so you can override a single
parameter without losing the rest.

Preview reading (``preview.read``)
====================================

Controls how :py:class:`~eomatch.preview.BuildMUPreview` reads products
when generating preview images.  Kept separate from ``read`` so that
lightweight preview reads do not affect scientific dataset builds.

The package default requests only the RGB bands with metadata disabled.  The
``"rgb"`` sentinel is resolved by ``eoio`` to the natural-colour bands for
each collection (``B02``/``B03``/``B04`` for S2, ``B2``/``B3``/``B4`` for
Landsat).

.. code-block:: yaml

   preview:
     read:
       defaults:
         vars_sel:
           meas: rgb     # must be a string, not a list
           aux: []
         read_params:
           use_chunks: false
           metadata_level: false
           save_extracted: false
         processors: {}
       collections: {}

Per-run config files
#####################

All CLI commands accept ``--config PATH`` to load an additional YAML file on
top of your user config.  This is the recommended way to supply run-specific
settings (time range, platforms, catalogue path) without modifying your
persistent user config:

.. code-block:: bash

   eomatch-find --config my_run.yaml
   eomatch-download --config my_run.yaml
   eomatch-preview /data/my_catalogue/catalog.json --config my_run.yaml

A minimal per-run file typically looks like:

.. code-block:: yaml

   platforms: Sentinel-2A, Landsat-9
   collections: S2_MSI_L1C, LANDSAT_C2L1
   start_time: "2023-06-01 00:00:00"
   end_time:   "2023-06-30 23:59:59"
   orbitx_netcdf_path: /data/orbitx/2023_S2A_LS9.nc

   matchup_catalogue:
     path: /data/my_catalogue

See ``example/find_and_catalogue.yaml`` in the repository for a fully
annotated example.

Configuring from Python
########################

Pass a path or a dict directly to
:py:class:`~eomatch.context.EOMatchContext`:

.. code-block:: python

   from eomatch import EOMatchContext

   # Load from a YAML file (merged on top of user config)
   ctx = EOMatchContext("my_run.yaml")

   # Or pass overrides as a dict
   ctx = EOMatchContext({
       "platforms": "Sentinel-2A, Landsat-9",
       "collections": "S2_MSI_L1C, LANDSAT_C2L1",
       "matchup_catalogue": {"path": "/data/my_catalogue"},
   })
