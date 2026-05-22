.. _datasets:

###########################
Building collocated datasets
###########################

Once you have a :py:class:`~eomatch.Matchup`, you can download the
underlying products and read them into a collocated dataset with a single
call:

.. code-block:: python

   from eomatch import EOMatchContext
   from eomatch.finder.sat2sat import Sat2SatMUFinder

   ctx = EOMatchContext("my_config.yaml")
   events = Sat2SatMUFinder(context=ctx).finder()

   mu = events[0].matchup_set[0]
   ds = mu.return_matchup_dataset()
   print(ds)

.. code-block:: text

   DataTree('None', parent=None)
   ├── DataTree('sensor_1')
   │   └── ... (variables for product 1)
   └── DataTree('sensor_2')
       └── ... (variables for product 2)

The returned object is an :py:class:`xarray.DataTree` with one node per
sensor (``sensor_1``, ``sensor_2``, …).  Each node contains the data read by
``eoio`` for that product, clipped to the collocation region.

Products are downloaded automatically if they are not already present on disk.
The download destination and API credentials are read from the
:py:class:`~eomatch.EOMatchContext`.

Controlling what is read
########################

:py:meth:`~eomatch.Matchup.return_matchup_dataset` accepts an optional
``collection_read_args`` argument that overrides what ``eoio`` reads on a
per-collection basis.  Because each collection uses different variable names
(e.g. ``B02`` in Sentinel-2, ``B2`` in Landsat), overrides are always keyed
by STAC collection ID.

Per-collection defaults can be set in the config under the ``read`` key
(see :ref:`read_config`), so you rarely need to pass ``collection_read_args``
explicitly.  When you do, each collection entry may contain any of:

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Key
     - Behaviour
     - Notes
   * - ``vars_sel``
     - **Full replacement**
     - Replaces the config-resolved value entirely for that collection. Use
       this to control exactly which variables are loaded into memory.
   * - ``read_params``
     - **Sub-key merge**
     - Merged on top of the config-resolved value. Only the keys you supply
       are overridden; others keep their config (or default) values.
   * - ``processors``
     - **Full replacement**
     - Replaces the config-resolved value entirely for that collection. Only
       the processors you name here will run.

**Select specific bands per collection**:

.. code-block:: python

   dt = mu.return_matchup_dataset(
       collection_read_args={
           "S2_MSI_L1C":   {"vars_sel": {"meas": ["B02", "B03", "B04", "B08"]}},
           "LANDSAT_C2L1": {"vars_sel": {"meas": ["B2",  "B3",  "B4",  "B5" ]}},
       }
   )

**Apply processors to one collection only**:

.. code-block:: python

   dt = mu.return_matchup_dataset(
       collection_read_args={
           "S2_MSI_L1C": {"processors": {"toa_reflectance": {}}},
       }
   )

**Nudge a read parameter for one collection** — ``read_params`` within a
collection entry merges at the sub-key level:

.. code-block:: python

   dt = mu.return_matchup_dataset(
       collection_read_args={
           "LANDSAT_C2L1": {"read_params": {"use_chunks": True}},
       }
   )

.. _read_config:

Configuring read defaults
#########################

The ``read`` section of your config file sets per-collection defaults so you
do not have to repeat them at every call site.  Global defaults apply to all
collections; per-collection entries are merged on top.

.. code-block:: yaml

   read:
     defaults:
       vars_sel:
         meas: []   # empty list = read all available measurement variables
         aux: []
       read_params:
         use_chunks: false
         metadata_level: true
         save_extracted: false
       processors: {}

     collections:
       LANDSAT_C2L1:
         vars_sel:
           meas: [B2, B3, B4, B5]
       S2_MSI_L1C:
         vars_sel:
           meas: [B02, B03, B04, B8A]

The merge order (lowest → highest priority) is:

1. Hardcoded fallbacks (``meas: []``, ``aux: []``, etc.)
2. ``read.defaults`` from the config
3. ``read.collections.<collection_id>`` from the config
4. Call-time arguments passed to :py:meth:`~eomatch.Matchup.return_matchup_dataset`

Building datasets in bulk
##########################

To build datasets for all matchups found in a run, iterate over the events:

.. code-block:: python

   for event in events:
       for mu in event.matchup_set:
           ds = mu.return_matchup_dataset()
           # process or save ds ...
