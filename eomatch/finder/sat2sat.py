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
from shapely.geometry import box as shapely_box

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
        issued per platform.  The query geometry is the configured site bounding
        box (``min_lat``/``max_lat``/``min_lon``/``max_lon`` in the context) when
        one is set, falling back to the event's own geometry otherwise — the
        event geometry from orbitx can be hundreds of km wide (returning products
        outside the site) or narrower than the site on one axis (missing products
        that do cover the site), whereas the event bbox has already passed
        :py:meth:`filter_events` so searching the full site bbox is safe.

        Products returned by scrappi are further filtered to those whose
        ``platform`` matches the platform the query was issued for — a
        collection can cover more than one platform (e.g. ``LANDSAT_C2L1``,
        which contains both Landsat-8 and Landsat-9 products), so without this
        filter a query for one platform could return products for another.
        This relies on scrappi returning ``product.platform`` values in the
        same short-code form used by ``platforms`` in the config and passed to
        orbitx (e.g. ``S2A``, ``LS9``) — see ``parse_platform_from_name`` in
        scrappi's ``BaseAPICallHandler``.

        Products returned for each platform are combined via a Cartesian
        product and those where all products geometrically overlap become
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
                site_bbox_configured = (
                    self.context["max_lat"]
                    and self.context["min_lat"]
                    and self.context["max_lon"]
                    and self.context["min_lon"]
                )
                if site_bbox_configured:
                    geom_shapely = shapely_box(
                        float(self.context["min_lon"]),
                        float(self.context["min_lat"]),
                        float(self.context["max_lon"]),
                        float(self.context["max_lat"]),
                    )
                else:
                    geom = query["geom"]
                    geom_shapely = shapely_box(
                        geom["longitude_minimum"],
                        geom["latitude_minimum"],
                        geom["longitude_maximum"],
                        geom["latitude_maximum"],
                    )
                try:
                    products = self.run_scrappi(query={**query, "geom": geom_shapely})
                except Exception as e:
                    warnings.warn(f"Scrappi query failed for event {mu_event}, platform {platform}: {e}")
                    continue
                n_kept = 0
                for p in products:
                    if p.platform == platform:
                        products_by_platform[platform].add_ProductItem(p)
                        n_kept += 1
                log.debug(
                    "  platform=%s: %d returned by scrappi, %d kept after platform filter",
                    platform,
                    len(products),
                    n_kept,
                )

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
           May contain Python format-string placeholders (e.g. ``{year}``,
           ``{platforms}``), letting one config path resolve to a different
           cache file per run.
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
            netcdf_path = netcdf_path.format(year=str(start.astype("datetime64[Y]")), platforms="_".join(platforms))
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
            propagation_sampling_interval=np.timedelta64(self.context["propagation_sampling_interval"], "s"),
            interpolation_sampling_interval=np.timedelta64(self.context["interpolation_sampling_interval"], "s"),
            space_diff_threshold=float(self.context["space_diff_threshold"]),
            time_diff_threshold=np.timedelta64(self.context["time_diff_threshold"], "s"),
            check_before=self.context["check_before"],
            check_after=self.context["check_after"],
            has_land_ocean_mask=self.context["has_land_ocean_mask"],
            custom_satellites=self.context["custom_satellites"] or [],
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
        (``[lon_min, lat_min, lon_max, lat_max]``).

        Applies each filter in :py:attr:`_EVENT_FILTER_METHODS` in turn and
        keeps events that pass all of them.  Each filter method is
        self-contained — it reads whichever context keys it needs and returns
        every event index when it isn't configured/enabled — so adding a new
        filter only means adding one more method and listing it in
        :py:attr:`_EVENT_FILTER_METHODS`; this method itself does not need to
        change.

        :param data: raw event dicts from ``orbitx.matchups.Matchups.events``.
        :return: filtered list of event dicts.
        """
        if not data:
            return []

        indices = np.arange(len(data))
        for filter_method_name in self._EVENT_FILTER_METHODS:
            idx = getattr(self, filter_method_name)(data)
            indices = np.intersect1d(indices, idx)

        return [data[i] for i in indices]

    _EVENT_FILTER_METHODS = (
        "_filter_lat",
        "_filter_lon",
        "_filter_antimeridian",
        "_filter_time",
        "_filter_solar_time",
    )

    def _filter_lat(self, data: List[Dict[str, Any]]) -> np.ndarray:
        """Keep events whose bbox overlaps ``[min_lat, max_lat]`` (overlap semantics).

        Returns every event index when ``min_lat``/``max_lat`` are not both set.

        :param data: raw event dicts.
        :return: array of indices into *data* that pass this filter.
        """
        if not (self.context["max_lat"] and self.context["min_lat"]):
            return np.arange(len(data))
        max_lat = float(self.context["max_lat"])
        min_lat = float(self.context["min_lat"])
        bbox_lat_mins = np.array([d["bbox"][1] for d in data])
        bbox_lat_maxs = np.array([d["bbox"][3] for d in data])
        return np.where((bbox_lat_mins < max_lat) & (bbox_lat_maxs > min_lat))[0]

    def _filter_lon(self, data: List[Dict[str, Any]]) -> np.ndarray:
        """Keep events whose bbox overlaps ``[min_lon, max_lon]`` (overlap semantics).

        Returns every event index when ``min_lon``/``max_lon`` are not both set.

        :param data: raw event dicts.
        :return: array of indices into *data* that pass this filter.
        """
        if not (self.context["max_lon"] and self.context["min_lon"]):
            return np.arange(len(data))
        max_lon = float(self.context["max_lon"])
        min_lon = float(self.context["min_lon"])
        bbox_lon_mins = np.array([d["bbox"][0] for d in data])
        bbox_lon_maxs = np.array([d["bbox"][2] for d in data])
        return np.where((bbox_lon_mins < max_lon) & (bbox_lon_maxs > min_lon))[0]

    def _filter_antimeridian(self, data: List[Dict[str, Any]]) -> np.ndarray:
        """Drop events whose bbox spans more than 180° of longitude.

        orbitx reports polar-orbit crossovers whose minimum bounding rectangle
        wraps the antimeridian and spans close to 360° of longitude.  These
        trivially pass any longitude intersection test (e.g. in
        :py:meth:`_filter_lon`) but the actual crossover is near a pole, not
        the site.

        Enabled by the ``exclude_antimeridian_events`` config flag (default
        ``False`` — off, since it is not always wanted, e.g. for polar
        research use cases).  Returns every event index when disabled.

        :param data: raw event dicts.
        :return: array of indices into *data* that pass this filter.
        """
        if not self.context.get("exclude_antimeridian_events", False):
            return np.arange(len(data))
        bbox_lon_mins = np.array([d["bbox"][0] for d in data])
        bbox_lon_maxs = np.array([d["bbox"][2] for d in data])
        return np.where((bbox_lon_maxs - bbox_lon_mins) <= 180)[0]

    def _filter_time(self, data: List[Dict[str, Any]]) -> np.ndarray:
        """Keep events whose window overlaps ``[start_time, end_time]`` (overlap semantics).

        ``start_time`` and ``end_time`` are each optional and applied
        independently; either or both may be unset.

        :param data: raw event dicts.
        :return: array of indices into *data* that pass this filter.
        """
        indices = np.arange(len(data))
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

        return indices

    def _filter_solar_time(self, data: List[Dict[str, Any]]) -> np.ndarray:
        """Drop events whose UTC window falls entirely outside local daytime at the site.

        Optical satellites cannot image at night, so events entirely outside
        04:00–20:00 local solar time at the site centre are dropped.

        Enabled by the ``exclude_night_events`` config flag (default
        ``False`` — off, since not every mission is optical-only) and only
        applied when a longitude filter (``min_lon``/``max_lon``) is
        configured, since local solar time is computed relative to the
        site's longitude.  Returns every event index otherwise.

        :param data: raw event dicts.
        :return: array of indices into *data* that pass this filter.
        """
        solar_time_enabled = self.context.get("exclude_night_events", False)
        if not (self.context["min_lon"] and self.context["max_lon"] and solar_time_enabled):
            return np.arange(len(data))

        site_lon = (float(self.context["min_lon"]) + float(self.context["max_lon"])) / 2.0
        solar_offset_h = site_lon / 15.0  # hours east of UTC
        lst_min, lst_max = 4.0, 20.0  # local solar time window (hours): exclude nighttime only
        utc_min = (lst_min - solar_offset_h) % 24
        utc_max = (lst_max - solar_offset_h) % 24

        event_start_times = np.array([d["start_time"] for d in data])
        event_stop_times = np.array([d["stop_time"] for d in data])
        # Fractional UTC hour of day for event start and stop
        start_h = (event_start_times.astype("datetime64[s]").astype(np.int64) % 86400) / 3600.0
        stop_h = (event_stop_times.astype("datetime64[s]").astype(np.int64) % 86400) / 3600.0

        if utc_min < utc_max:
            # Normal case: window does not cross midnight
            return np.where((start_h < utc_max) & (stop_h > utc_min))[0]
        else:
            # Window crosses midnight (sites far west/east of UTC)
            return np.where((start_h < utc_max) | (stop_h > utc_min))[0]

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
