"""eomatch.finder.sat2sat - identification and indexing of collocated satellite products"""

import logging
import orbitx
import scrappi
import datetime
from eomatch.domain import Matchup, MatchupSet, MatchupEvent, _matchup_collection_id
import numpy as np
import warnings
from typing import Dict, Any, List
from eomatch.finder.base import BaseMUFinder
from collections import defaultdict
import itertools

__all__ = ["Sat2SatMUFinder"]

log = logging.getLogger(__name__)


class Sat2SatMUFinder(BaseMUFinder):
    """Finder for collocated pairs of satellite image products.

    Wraps the full satellite-to-satellite matchup discovery pipeline:

    1. Run ``orbitx`` (or load a cached NetCDF) to obtain crossover events.
    2. Filter events against the spatial/temporal bounds in the context config.
    3. Convert each event to a :py:class:`~eomatch.domain.MatchupEvent`.
    4. For each event, query ``scrappi`` per platform, check geometric overlap,
       and build :py:class:`~eomatch.domain.Matchup` objects.
    5. Return the full list of :py:class:`~eomatch.domain.MatchupEvent` objects,
       each carrying its :py:class:`~eomatch.domain.MatchupSet`.

    Example usage::

        from eomatch import EOMatchContext
        from eomatch.finder.sat2sat import Sat2SatMUFinder

        ctx = EOMatchContext("my_config.yaml")
        finder = Sat2SatMUFinder(context=ctx)
        events = finder.finder()
    """

    def finder(self) -> List[MatchupEvent]:
        """Run the full matchup discovery pipeline.

        Calls :py:meth:`get_orbitx_ds`, :py:meth:`filter_events`,
        :py:meth:`to_matchup_event`, and :py:meth:`to_matchup_set` in sequence.

        :return: list of :py:class:`~eomatch.domain.MatchupEvent` objects, each
            with its :py:attr:`~eomatch.domain.MatchupEvent.matchup_set` populated.
        """
        orbitx_ds = self.get_orbitx_ds()
        events = self.filter_events(orbitx_ds.events)
        mu_events = self.to_matchup_event(events)
        return self.to_matchup_set(mu_events)

    def to_matchup_set(self, mu_events: List[MatchupEvent]) -> List[MatchupEvent]:
        """Query scrappi for each event and build per-event :py:class:`~eomatch.domain.MatchupSet` objects.

        For each :py:class:`~eomatch.domain.MatchupEvent`, one scrappi query is
        issued per platform.  Products returned for each platform are combined via
        a Cartesian product and those where all products geometrically overlap become
        :py:class:`~eomatch.domain.Matchup` objects.  Events for which fewer than
        two platforms return products are skipped.

        :param mu_events: list of :py:class:`~eomatch.domain.MatchupEvent` objects
            to query.
        :return: the same list with :py:attr:`~eomatch.domain.MatchupEvent.matchup_set`
            populated for events that produced at least one matchup.
        """
        muset_events = []

        for mu_event in mu_events:
            log.debug("Processing matchup event: %s", mu_event)

            mus_event = MatchupSet()

            # Run one Scrappi query per collection/platform pair
            products_by_platform: defaultdict[str, scrappi.ProductItemSet] = defaultdict(scrappi.ProductItemSet)
            for query in mu_event.get_scrappi_queries():
                platform = query["platform"]
                try:
                    products = self.run_scrappi(query=query)
                except Exception as e:
                    warnings.warn(f"Scrappi query failed for event {mu_event}, platform {platform}: {e}")
                    continue
                for p in products:
                    products_by_platform[platform].add_ProductItem(p)

            # Check that products were found for at least 2 platforms
            platform_product_sets = list(products_by_platform.values())
            if len(platform_product_sets) < 2:
                log.debug("Incomplete platform coverage for event %s — skipping", mu_event)
                continue

            # Cartesian product over platforms — generates all candidate matchups
            for combination in itertools.product(*platform_product_sets):
                if self.all_products_overlap(list(combination)):
                    mu = Matchup(scrappi.ProductItemSet(list(combination)))
                    mus_event.append(mu)

            mu_event.matchup_set = mus_event
            muset_events.append(mu_event)

        return muset_events

    def has_products(self, product_array) -> bool:
        """Return ``True`` if *product_array* is non-None and non-empty.

        :param product_array: array-like of products, or ``None``.
        :return: ``True`` if at least one product is present.
        """
        return product_array is not None and len(product_array) > 0

    def get_orbitx_ds(self) -> "orbitx.matchups.Matchups":
        """Return an ``orbitx`` matchup dataset, either from a cached NetCDF or by running the propagator.

        The NetCDF path is resolved in priority order:

        1. ``orbitx_netcdf_files.<combo-id>`` in the config, where ``<combo-id>``
           is the platform-aware collection pair ID
           (e.g. ``LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A``).
        2. ``orbitx_netcdf_path`` in the config (flat fallback, backwards-compatible).
        3. If neither is set, the propagator is run from scratch.

        When a NetCDF path is found, the file is loaded and its
        ``start_date`` / ``end_date`` are compared against the requested
        ``start_time`` / ``end_time`` from the config.  If the file does not
        fully cover the requested period the propagator is run instead and a
        warning is logged.

        :return: ``orbitx.matchups.Matchups`` dataset containing crossover events.
        """
        platforms = self.context["platforms"].replace(" ", "").split(",")
        collections = self.context["collections"].replace(" ", "").split(",")
        start = np.datetime64(self.context["start_time"])
        end = np.datetime64(self.context["end_time"])

        combo_id = _matchup_collection_id(collections, platforms)
        netcdf_files = self.context.get("orbitx_netcdf_files") or {}
        netcdf_path = netcdf_files.get(combo_id) or self.context.get("orbitx_netcdf_path")

        if netcdf_path:
            log.debug("Loading orbitx NetCDF for %s: %s", combo_id, netcdf_path)
            orbitx_ds = orbitx.matchups.Matchups.from_netcdf(netcdf_path)
            if self._netcdf_covers_period(orbitx_ds, start, end):
                return orbitx_ds
            log.warning(
                "orbitx NetCDF for %s covers %s – %s but requested period is %s – %s; running propagator instead.",
                combo_id,
                orbitx_ds.start_date,
                orbitx_ds.end_date,
                start,
                end,
            )

        log.debug("Running orbitx propagator for %s", combo_id)
        return orbitx.matchups.Matchups.find_matchups(
            satellites=platforms,
            start_date=start,
            end_date=end,
            propagation_sampling_interval=np.timedelta64(self.context["propagation_sampling_interval"]),
            interpolation_sampling_interval=np.timedelta64(self.context["interpolation_sampling_interval"]),
            space_diff_threshold=float(self.context["space_diff_threshold"]),
            time_diff_threshold=np.timedelta64(self.context["time_diff_threshold"]),
            check_before=self.context["check_before"],
            check_after=self.context["check_after"],
            has_land_ocean_mask=self.context["has_land_ocean_mask"],
            custom_satellites=self.context["custom_satellites"],
            dump_orbit=self.context["dump_orbit"],
        )

    @staticmethod
    def _netcdf_covers_period(
        orbitx_ds: "orbitx.matchups.Matchups",
        start: np.datetime64,
        end: np.datetime64,
    ) -> bool:
        """Return ``True`` if *orbitx_ds* fully covers ``[start, end]``.

        :param orbitx_ds: loaded ``orbitx.matchups.Matchups`` dataset.
        :param start: requested period start as ``np.datetime64``.
        :param end: requested period end as ``np.datetime64``.
        :return: ``True`` if ``orbitx_ds.start_date <= start`` and
            ``orbitx_ds.end_date >= end``.
        """
        return bool(orbitx_ds.start_date <= start and orbitx_ds.end_date >= end)

    def filter_events(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter a list of raw orbitx events against the bounds in the context config.

        Events are dicts with keys ``start_time``, ``stop_time``, and ``bbox``
        (``[lon_min, lat_min, lon_max, lat_max]``).  Time filters use overlap
        semantics — an event is retained if its window intersects
        ``[start_time, end_time]``.  Spatial filters compare the bbox centre point
        against ``[min_lat, max_lat]`` and ``[min_lon, max_lon]``.

        :param data: raw event dicts from ``orbitx.matchups.Matchups.events``.
        :return: filtered list of event dicts.
        """
        if not data:
            return []

        indices = np.arange(len(data))

        # -------- LAT FILTER (bbox centre) --------
        if self.context["max_lat"] and self.context["min_lat"]:
            max_lat = float(self.context["max_lat"])
            min_lat = float(self.context["min_lat"])
            lats = np.array([(d["bbox"][1] + d["bbox"][3]) / 2 for d in data])
            idx = np.where((lats < max_lat) & (lats > min_lat))[0]
            indices = np.intersect1d(indices, idx)

        # -------- LON FILTER (bbox centre) --------
        if self.context["max_lon"] and self.context["min_lon"]:
            max_lon = float(self.context["max_lon"])
            min_lon = float(self.context["min_lon"])
            lons = np.array([(d["bbox"][0] + d["bbox"][2]) / 2 for d in data])
            idx = np.where((lons < max_lon) & (lons > min_lon))[0]
            indices = np.intersect1d(indices, idx)

        # -------- TIME FILTERS (overlap) --------
        # Keep events whose window overlaps [filter_start, filter_end].
        if self.context["start_time"]:
            filter_start = np.datetime64(datetime.datetime.strptime(self.context["start_time"], "%Y-%m-%d %H:%M:%S"))
            event_stop_times = np.array([d["stop_time"] for d in data])
            idx = np.where(event_stop_times > filter_start)[0]
            indices = np.intersect1d(indices, idx)

        if self.context["end_time"]:
            filter_end = np.datetime64(datetime.datetime.strptime(self.context["end_time"], "%Y-%m-%d %H:%M:%S"))
            event_start_times = np.array([d["start_time"] for d in data])
            idx = np.where(event_start_times < filter_end)[0]
            indices = np.intersect1d(indices, idx)

        return [data[i] for i in indices]

    def to_matchup_event(self, events: List[Dict[str, Any]]) -> List[MatchupEvent]:
        """Convert raw orbitx event dicts to :py:class:`~eomatch.domain.MatchupEvent` objects.

        Platforms and collections are read from the context config.  Spatial bounds
        are taken from the ``bbox`` key of each event dict.

        :param events: filtered event dicts as returned by :py:meth:`filter_events`.
        :return: list of :py:class:`~eomatch.domain.MatchupEvent` objects.
        """
        mu_events = []
        for event in events:
            mu_event = MatchupEvent(
                platforms=self.context["platforms"].replace(" ", "").split(","),
                collections=self.context["collections"].replace(" ", "").split(","),
                start_time=event["start_time"],
                stop_time=event["stop_time"],
                latitude_maximum=event["bbox"][3],
                latitude_minimum=event["bbox"][1],
                longitude_maximum=event["bbox"][2],
                longitude_minimum=event["bbox"][0],
            )

            mu_events.append(mu_event)

        return mu_events


if __name__ == "__main__":
    pass
