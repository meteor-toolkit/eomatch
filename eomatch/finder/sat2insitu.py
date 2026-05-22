"""eomatch.finder.sat2insitu - identification and indexing of collocated satellite and in-situ products"""

import scrappi
import datetime
from eomatch.domain import Matchup, MatchupSet, MatchupEvent
import numpy as np
import warnings
from typing import List
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from eomatch.finder.base import BaseMUFinder
from collections import defaultdict
import itertools

__author__ = "Pieter De Vis"
__all__ = ["Sat2InSituMUFinder"]


class Sat2InSituMUFinder(BaseMUFinder):
    """
    Routine for identifying and indexing collocated pairs of satellite image products
    """

    def finder(self) -> List[MatchupEvent]:
        """
        Function to find all matchups and return them as a MatchupSet and store json files
        """
        # first generate list of matchup events using orbitx
        mu_events = self.identify_mu_events()
        muset_events = self.to_matchup_set(mu_events)
        return muset_events

    def to_matchup_set(self, mu_events) -> List[MatchupEvent]:

        muset_events = []

        for mu_event in mu_events:
            print("processing matchup event:", mu_event)

            mus_event = MatchupSet()

            # Run one Scrappi query per collection/platform pair
            products_by_platform: defaultdict[str, scrappi.ProductItemSet] = defaultdict(scrappi.ProductItemSet)
            for query in mu_event.get_scrappi_queries():
                platform = query["platform"]
                try:
                    products = self.run_scrappi(query=query, context={})
                except Exception as e:
                    warnings.warn(f"Scrappi query failed for event {mu_event}, platform {platform}: {e}")
                    continue
                for p in products:
                    products_by_platform[platform].add_ProductItem(p)

            # Check that products were found for at least 2 platforms
            platform_product_sets = list(products_by_platform.values())
            if len(platform_product_sets) < 2:
                print(f"Incomplete platform coverage for event {mu_event}")
                continue

            # Cartesian product over platforms — generates all candidate matchups
            for combination in itertools.product(*platform_product_sets):
                if self.all_products_overlap(list(combination)):
                    mu = Matchup(scrappi.ProductItemSet(list(combination)))
                    mus_event.append(mu)

            mu_event.matchup_set = mus_event
            muset_events.append(mu_event)

        return muset_events

    def has_products(self, product_array):
        return product_array is not None and len(product_array) > 0

    def identify_mu_events(self) -> List[MatchupEvent]:
        """
        Function to identify matchups events between insitu and satelite data and store into MatchupEvents
        """
        # # first get the ROI for the in situ data
        platforms = self.context.get_config_value("platforms").replace(" ", "").split(",")
        collections = self.context.get_config_value("collections").replace(" ", "").split(",")

        for collection in collections:
            if scrappi.is_insitu_collection(collection):
                apis = scrappi.list_available_apis(collection)
                if apis >= 1:
                    api = apis[0]
                else:
                    raise ValueError(f"no api found for collection {collection}")
                insitu_roi = api.get_roi_shapely(platforms)
            else:
                sat_collection = collection

        query = {}
        query["collection"] = sat_collection
        query["geom"] = insitu_roi
        query["start_time"] = datetime.datetime.strptime(
            self.context.get_config_value("start_time"), "%Y-%m-%d %H:%M:%S"
        )
        query["stop_time"] = datetime.datetime.strptime(self.context.get_config_value("end_time"), "%Y-%m-%d %H:%M:%S")
        products = self.run_scrappi(query, context={})

        # parse matchup events
        product_indices = self.parse_matchup_events(products)

        mu_events = []
        for i in range(len(product_indices) - 1):
            mu_event = MatchupEvent(
                platforms=platforms,
                collections=collections,
                start_time=products[product_indices[i]].start_time
                - datetime.timedelta(seconds=self.context.get_config_value("time_diff_threshold")),
                stop_time=products[product_indices[i + 1] - 1].stop_time
                + datetime.timedelta(seconds=self.context.get_config_value("time_diff_threshold")),
                latitude_minimum=np.min(
                    [prod.geometry.bounds[1] for prod in products[product_indices[i] : product_indices[i + 1] - 1]]
                ),
                longitude_minimum=np.min(
                    [prod.geometry.bounds[0] for prod in products[product_indices[i] : product_indices[i + 1] - 1]]
                ),
                latitude_maximum=np.max(
                    [prod.geometry.bounds[3] for prod in products[product_indices[i] : product_indices[i + 1] - 1]]
                ),
                longitude_maximum=np.max(
                    [prod.geometry.bounds[2] for prod in products[product_indices[i] : product_indices[i + 1] - 1]]
                ),
                context=self.context,
            )
            mu_events.append(mu_event)

        return mu_events

    def parse_matchup_events(self, products):
        """ """
        product_indices = [0]
        for i in range(len(products)):
            if (i == len(products) - 1) or (
                products[i + 1].start_time - products[i].stop_time
                > np.timedelta64(self.context.get_config_value("time_diff_threshold"), "s")
            ):
                product_indices.append(i + 1)

        return product_indices

    def plot_matchup_event(self, path, matchupset):
        plt.figure()
        ax = plt.axes(projection=ccrs.PlateCarree())
        plt.title(
            "Matchup Event between %s \n and %s"
            % (
                matchupset._matchups[0]._products[0].start_time,
                matchupset._matchups[-1]._products[-1].stop_time,
            )
        )
        matchupset.plot_geometries(ax)
        plt.legend()
        plt.savefig(path)
        plt.clf()


if __name__ == "__main__":
    pass
