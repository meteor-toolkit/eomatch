.. currentmodule:: eomatch

.. _api:

#############
API reference
#############

This page provides an auto-generated summary of **eomatch**'s API.
For more details and examples, refer to the relevant chapters in the user guide.

Domain model
------------

.. autosummary::
   :toctree: generated/

   MatchupEvent
   MatchupEvent.to_stac_item
   MatchupEvent.from_stac_item
   MatchupEvent.get_scrappi_queries
   MatchupEvent.stac_id
   MatchupEvent.platformstring

   MatchupEventSet

   Matchup
   Matchup.collocation_region
   Matchup.product_time_bounds
   Matchup.time_diff_abs
   Matchup.time_diff
   Matchup.return_matchup_dataset
   Matchup.to_stac_item
   Matchup.from_stac_item
   Matchup.stac_id

   MatchupSet
   MatchupSet.collections

Discovery
---------

.. currentmodule:: eomatch.finder.sat2sat

.. autosummary::
   :toctree: generated/

   Sat2SatMUFinder
   Sat2SatMUFinder.finder
   Sat2SatMUFinder.get_orbitx_ds
   Sat2SatMUFinder.filter_events
   Sat2SatMUFinder.to_matchup_event
   Sat2SatMUFinder.to_matchup_set

Cataloguing
-----------

.. currentmodule:: eomatch.mu_stac

.. autosummary::
   :toctree: generated/

   MatchupCatalogue
   MatchupCatalogue.add_event
   MatchupCatalogue.add_matchup
   MatchupCatalogue.get_events
   MatchupCatalogue.save
   MatchupCatalogue.open
   MatchupCatalogue.download_products
   MatchupCatalogue.add_product_asset
   MatchupCatalogue.add_event_asset
   MatchupCatalogue.add_matchup_asset
   MatchupCatalogue.add_matchup_collection_asset
   MatchupCatalogue.add_event_collection_asset
   MatchupCatalogue.remove_product_asset
   MatchupCatalogue.remove_event_asset
   MatchupCatalogue.remove_matchup_asset
   MatchupCatalogue.remove_matchup_collection_asset
   MatchupCatalogue.remove_event_collection_asset

Central catalogue
-----------------

.. currentmodule:: eomatch.ingest

.. autosummary::
   :toctree: generated/

   ingest

.. currentmodule:: eomatch.query

.. autosummary::
   :toctree: generated/

   query

Enrichment
----------

.. currentmodule:: eomatch.enrich

.. autosummary::
   :toctree: generated/

   enrich

.. currentmodule:: eomatch.enrich.time_diff

.. autosummary::
   :toctree: generated/

   time_diff

.. currentmodule:: eomatch.enrich.geometric

.. autosummary::
   :toctree: generated/

   geometric

.. currentmodule:: eomatch.enrich.solar_elevation

.. autosummary::
   :toctree: generated/

   solar_elevation

.. currentmodule:: eomatch.enrich.land_fraction

.. autosummary::
   :toctree: generated/

   land_fraction

Pipeline
--------

.. currentmodule:: eomatch.find_and_catalogue

.. autosummary::
   :toctree: generated/

   find_and_catalogue
