.. _finding_matchups:

#################
Finding matchups
#################

A *matchup* is a pair (or group) of satellite image products that overlap in
both space and time.  EOMatch identifies them in two stages:

1. **Orbit crossover detection** — `orbitx` propagates satellite orbits and
   returns candidate *matchup events*: time windows and bounding boxes where
   two (or more) satellites are close enough to produce overlapping products.
2. **Product discovery** — for each event, `scrappi` queries the product
   catalogue and filters results down to products whose footprints actually
   intersect.

The result is a list of :py:class:`~eomatch.MatchupEvent` objects, each
with an attached :py:class:`~eomatch.MatchupSet` of confirmed
:py:class:`~eomatch.Matchup` objects.

Running the finder
##################

Use :py:class:`~eomatch.finder.sat2sat.Sat2SatMUFinder` to run the full
pipeline.  Parameters are read from a
:py:class:`~eomatch.EOMatchContext`:

.. code-block:: python

   from eomatch import EOMatchContext
   from eomatch.finder.sat2sat import Sat2SatMUFinder

   ctx = EOMatchContext("my_config.yaml")
   events = Sat2SatMUFinder(context=ctx).finder()

   for event in events:
       print(event)
       for matchup in event.matchup_set:
           print("  ", matchup)

.. code-block:: text

   <eomatch.MatchupEvent (S2A_S3A, times: [...], bounds: {...})
     <eomatch.Matchup (bounds: (...), start_time: 2023-06-15T10:12:03)>
     Products:
       LANDSAT_C2L1:  LC08_L1TP_...
       S3_EFR:        S3A_OL_1_EFR...
   ...

The ``platforms`` and ``collections`` config keys (comma-separated) control
which satellites and product collections are searched:

.. code-block:: yaml

   platforms: S2A, S3A
   collections: S2_MSI_L1C, S3_EFR
   start_time: "2023-06-01 00:00:00"
   end_time:   "2023-06-30 23:59:59"
   space_diff_threshold: 290          # km
   time_diff_threshold:  900          # seconds

Using a pre-computed orbitx file
#################################

Running `orbitx` can take time for long date ranges.  You can point eomatch
at a pre-computed NetCDF file to skip orbit propagation:

.. code-block:: yaml

   orbitx_netcdf_path: /data/matchups/S2A_S3A_2023-06.nc

Spatial and temporal filtering
################################

Events returned by `orbitx` can be further restricted before product queries
are issued.  Set any combination of the following keys in your config:

.. code-block:: yaml

   min_lat: 40.0
   max_lat: 70.0
   min_lon: -10.0
   max_lon: 30.0
   start_time: "2023-06-15 00:00:00"
   end_time:   "2023-06-15 23:59:59"

Two further filters are available to remove events that are unlikely to
produce usable results.  Both default to ``False`` (off), since they are not
always wanted — e.g. for polar research use cases, or missions that can image
at night:

.. code-block:: yaml

   exclude_antimeridian_events: true   # drop events whose bbox spans more
                                        # than 180° of longitude (antimeridian
                                        # / polar-crossover artefacts)
   exclude_night_events: true          # drop events entirely outside local
                                        # daytime at the site (requires
                                        # min_lon/max_lon to be set)

Inspecting a matchup
#####################

Each :py:class:`~eomatch.Matchup` exposes the geometry and timing of the
collocated products:

.. code-block:: python

   mu = events[0].matchup_set[0]

   # Shapely polygon of the overlapping footprint
   print(mu.collocation_region)

   # Earliest start time and latest stop time across all products
   print(mu.product_time_bounds)

   # Absolute time difference between product start times (seconds)
   print(mu.time_diff_abs)

   # Signed time difference: collection2.start - collection1.start (seconds)
   print(mu.time_diff("S3_EFR", "S2_MSI_L1C"))
