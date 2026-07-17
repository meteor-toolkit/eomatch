"""eomatch.finder.base - base class for finder implementations"""

from abc import abstractmethod
import scrappi
from eomatch.domain import MatchupEvent
import warnings
from processor_tools import BaseProcessor
from typing import Union, List, Optional
from scrappi import ScrappiContext, perform_query
from eomatch import EOMatchContext

__author__ = "Pieter De Vis"
__all__ = ["BaseMUFinder"]


class BaseMUFinder(BaseProcessor):
    """Abstract base class for collocated product identification routines.

    Subclasses implement :py:meth:`finder` to produce a list of
    :py:class:`~eomatch.domain.MatchupEvent` objects.  Common helpers
    (:py:meth:`run_scrappi`, :py:meth:`all_products_overlap`) are provided here.
    """

    def __init__(self, context: Optional[Union[dict, str]] = None) -> None:
        """Initialise the finder.

        :param context: :py:class:`~eomatch.context.EOMatchContext` (or a
            dict/path accepted by the parent ``BaseProcessor``) supplying runtime
            configuration.  Defaults to ``EOMatchContext()``.
        """
        if context is None:
            context = EOMatchContext()
        super(BaseMUFinder, self).__init__(context)

    @abstractmethod
    def finder(self) -> List[MatchupEvent]:
        """Run the matchup discovery pipeline and return the results.

        Must be overridden by subclasses.

        :return: list of :py:class:`~eomatch.domain.MatchupEvent` objects, each
            with its :py:attr:`~eomatch.domain.MatchupEvent.matchup_set` populated.
        """
        ...

    def run_scrappi(self, query: dict, context: Optional[dict] = None) -> scrappi.ProductItemSet:
        """Execute a single scrappi query and return the matching products.

        If the query returns no products an empty
        :py:class:`~scrappi.ProductItemSet` is returned rather than ``None``.
        Results are sorted by ``start_time`` before being returned.

        The ``platform`` key is stripped from the query before it is passed to
        scrappi.  Passing it through causes scrappi to forward it to eodag as a
        provider-level search filter (e.g. ``platformSerialIdentifier='A'`` on
        cop_dataspace) which frequently returns zero results.  Platform-level
        filtering is instead performed in the caller after products are returned.

        :param query: scrappi query dict (keys depend on the collection type).
        :param context: optional :py:class:`~scrappi.ScrappiContext`; defaults to
            ``ScrappiContext()``.
        :return: sorted :py:class:`~scrappi.ProductItemSet` of matching products.
        """
        if context is None:
            context = ScrappiContext()

        scrappi_query = {k: v for k, v in query.items() if k != "platform"}
        products = perform_query(scrappi_query, context)
        if products is None:
            return scrappi.ProductItemSet()
        products._products.sort(key=lambda prod: prod.start_time)
        return products

    def filter_overlapping_products(
        self, productitem: scrappi.ProductItem, productitemset: scrappi.ProductItemSet
    ) -> scrappi.ProductItemSet:
        """Return the subset of *productitemset* whose geometry overlaps *productitem*.

        Products with an empty intersection are excluded and a warning is issued.

        :param productitem: reference product to test against.
        :param productitemset: candidate products to filter.
        :return: :py:class:`~scrappi.ProductItemSet` containing only the overlapping products.
        """
        reg_1 = productitem.geometry
        out_productitemset = scrappi.ProductItemSet()
        for productitem2 in productitemset:
            col_reg = reg_1.intersection(productitem2.geometry)
            if col_reg.is_empty:
                warnings.warn("No intersection found")
            else:
                out_productitemset.add_ProductItem(productitem2)
        return out_productitemset

    def all_products_overlap(self, products: list[scrappi.ProductItem]) -> bool:
        """Return ``True`` if every pair of products in *products* has a non-empty geometric intersection.

        :param products: list of :py:class:`~scrappi.ProductItem` objects to check.
        :return: ``True`` if all products mutually overlap, ``False`` if any pair does not.
        """
        for i, p1 in enumerate(products):
            reg1 = p1.geometry
            for p2 in products[i + 1 :]:
                if reg1.intersection(p2.geometry).is_empty:
                    return False
        return True


if __name__ == "__main__":
    pass
