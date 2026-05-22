.. _previews:

#################
Preview images
#################

EOMatch can generate side-by-side natural-colour preview images for any
:py:class:`~eomatch.domain.Matchup`.  Previews use a lightweight read
configuration separate from the scientific dataset defaults — only the RGB
bands are loaded — so they are fast to produce even at full catalogue scale.

Generating a preview in Python
################################

Use :py:func:`~eomatch.preview.preview_matchup` to generate a preview for a
single matchup.  The function returns a :py:class:`matplotlib.figure.Figure`
(suitable for inline notebook display) and optionally saves the image to disk:

.. code-block:: python

   from eomatch import preview_matchup

   fig = preview_matchup(matchup)

.. code-block:: python

   fig = preview_matchup(matchup, output_path="preview.png", max_pixels=256)

The figure contains one panel per sensor, labelled with the STAC collection ID
(e.g. ``S2_MSI_L1C``, ``LANDSAT_C2L1``).  Each panel is a percentile-stretched
natural-colour composite derived from the collection's RGB bands.

Controlling what is read
#########################

:py:func:`~eomatch.preview.preview_matchup` accepts ``collection_read_args``
with the same semantics as
:py:meth:`~eomatch.domain.Matchup.return_matchup_dataset` (see
:ref:`datasets`):

.. code-block:: python

   fig = preview_matchup(
       matchup,
       collection_read_args={
           "S2_MSI_L1C": {"vars_sel": {"meas": ["B04", "B03", "B02"]}},
       },
   )

Configuring preview defaults
##############################

Preview reads are configured under the ``preview.read`` key in the config file,
independently of the ``read`` section used for scientific datasets.  The
bundled default requests only the RGB bands with metadata disabled:

.. code-block:: yaml

   preview:
     read:
       defaults:
         vars_sel:
           meas: rgb        # eoio resolves "rgb" to the natural-colour bands per collection
           aux: []
         read_params:
           use_chunks: false
           metadata_level: false
           save_extracted: false
         processors: {}
       collections: {}

The ``meas: rgb`` sentinel is resolved by ``eoio`` to the appropriate band
names for each collection (e.g. ``B02``, ``B03``, ``B04`` for ``S2_MSI_L1C``).
Per-collection overrides follow the same merge rules as the main ``read``
section (see :ref:`read_config`).

Generating thumbnails in bulk
##############################

The ``eomatch-preview`` command generates thumbnails for every downloaded
matchup in a catalogue and registers each as a ``"thumbnail"`` STAC asset on
the matchup Item.  Running the command repeatedly is safe — matchups that
already have a thumbnail are skipped automatically.

.. code-block:: bash

   eomatch-preview /data/my_catalogue/catalog.json

Thumbnails are saved under a ``thumbnails/`` directory inside the catalogue
root, mirroring the date hierarchy used by the ``data/`` folder:

.. code-block:: text

   catalogue/
   ├── data/
   │   └── Landsat/Landsat-9/LANDSAT_C2L1/2022/05/21/LC09_…
   └── thumbnails/
       └── LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A/
           └── 2022/
               └── 05/
                   └── 21/
                       └── <matchup-id>_thumbnail.png

Platform is included in the folder name so that matchups between different
platform pairs (e.g. Landsat-8 vs Sentinel-2B) are stored separately even when
they share the same collection pair.

The thumbnail path is stored as a relative ``href`` on the matchup STAC Item
so that the catalogue remains self-contained.

Available options:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Flag
     - Description
   * - ``CATALOGUE``
     - Path to the root ``catalog.json`` (required).
   * - ``--collections ID [ID …]``
     - Restrict to one sensor pair, e.g. ``S2_MSI_L1C LANDSAT_C2L1``.
   * - ``--platforms NAME [NAME …]``
     - Restrict to events that include at least one of these platforms.
   * - ``--start DATETIME``
     - Lower bound on event time (ISO 8601, e.g. ``2022-01-01``).
   * - ``--stop DATETIME``
     - Upper bound on event time (ISO 8601, e.g. ``2022-12-31``).
   * - ``--bbox LON_MIN LAT_MIN LON_MAX LAT_MAX``
     - Spatial bounding-box filter.
   * - ``--max-pixels N``
     - Maximum pixel extent in either dimension (default: 512).
   * - ``--overwrite``
     - Regenerate thumbnails even when one already exists.
   * - ``--config PATH``
     - YAML config file merged on top of the user config.
   * - ``--verbose`` / ``-v``
     - Enable debug logging.

The same functionality is available as a Python function:

.. code-block:: python

   from eomatch.generate_previews import generate_previews

   n = generate_previews(
       catalogue_path="/data/my_catalogue/catalog.json",
       collections=["S2_MSI_L1C", "LANDSAT_C2L1"],
       max_pixels=256,
   )
   print(f"Generated {n} thumbnail(s)")
