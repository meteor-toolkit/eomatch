"""eomatch.find_and_catalogue - discover matchups and persist them to a STAC catalogue"""

from __future__ import annotations

import argparse
import logging
from typing import Optional

from eomatch.context import EOMatchContext
from eomatch.finder.sat2sat import Sat2SatMUFinder
from eomatch.mu_stac import MatchupCatalogue

log = logging.getLogger(__name__)


def find_and_catalogue(
    context: Optional[EOMatchContext] = None,
    path: Optional[str] = None,
) -> MatchupCatalogue:
    """Run :py:class:`~eomatch.finder.sat2sat.Sat2SatMUFinder` and persist all found
    events and matchups to a STAC catalogue.

    Both the finder and the catalogue read from the same ``context``, so a single config
    covers the orbitx parameters (platforms, time range, thresholds) and the catalogue
    parameters (path, id, description).

    :param context: shared configuration; defaults to ``EOMatchContext()``.
    :param path: root directory to save the catalogue. Overrides ``matchup_catalogue.path``
        in the config when provided.
    :return: the populated :py:class:`~eomatch.mu_stac.MatchupCatalogue`.
    :raises ValueError: if no catalogue path is set via ``path`` or the config.
    """
    if context is None:
        context = EOMatchContext()

    log.info("Running Sat2SatMUFinder...")
    events = Sat2SatMUFinder(context=context).finder()

    n_matchups = sum(len(event.matchup_set) for event in events if event.matchup_set is not None)
    log.info("Found %d event(s) containing %d matchup(s) in total", len(events), n_matchups)

    catalogue = MatchupCatalogue(context=context, path=path)
    for event in events:
        catalogue.add_event(event)
        log.debug(
            "Added event %s (%d matchups)",
            event.stac_id,
            len(event.matchup_set) if event.matchup_set is not None else 0,
        )

    log.info("Saving catalogue to %s...", catalogue.path)
    catalogue.save()
    log.info("Done.")

    return catalogue


def main() -> None:
    """Entry point for the ``eomatch-find`` console script."""
    parser = argparse.ArgumentParser(description="Find satellite matchups and save to a STAC catalogue.")
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to a YAML config file. Merged on top of the user config.",
    )
    parser.add_argument(
        "--path",
        metavar="DIR",
        help="Root directory to save the catalogue. Overrides matchup_catalogue.path in config.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    context = EOMatchContext(args.config) if args.config else EOMatchContext()
    find_and_catalogue(context=context, path=args.path)


if __name__ == "__main__":
    main()
