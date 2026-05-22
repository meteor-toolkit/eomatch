.. currentmodule:: eomatch.finder.base

.. _internal_api:

############
Internal API
############

This page provides an auto-generated summary of **eomatch**'s internal
backend components.  These are not part of the public API and may change
without notice.

Finder base class
-----------------

:py:class:`~eomatch.finder.base.BaseMUFinder` is the abstract base for all
finder implementations.  It inherits from ``processor_tools.BaseProcessor``
and provides shared helpers for querying ``scrappi`` and filtering products by
geometric overlap.

.. autosummary::
   :toctree: generated/

   BaseMUFinder
   BaseMUFinder.finder
   BaseMUFinder.run_scrappi
   BaseMUFinder.filter_overlapping_products
   BaseMUFinder.all_products_overlap

Satellite-to-satellite finder internals
----------------------------------------

.. currentmodule:: eomatch.finder.sat2sat

.. autosummary::
   :toctree: generated/

   Sat2SatMUFinder.has_products
   Sat2SatMUFinder.plot_matchup_event
