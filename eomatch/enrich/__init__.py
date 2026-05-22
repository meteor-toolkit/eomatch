"""eomatch.enrich — apply enrichers to matchup STAC items.

Enrichers are callables that take a :py:class:`~eomatch.domain.Matchup`
and return a ``dict`` of property key/value pairs to add to the corresponding
STAC Item.  The updated properties are written back to the on-disk JSON files
so they persist and can be pushed to the central catalogue via
``eomatch-ingest``.

Built-in enrichers live as submodules of this package:

- :py:mod:`eomatch.enrich.time_diff`
- :py:mod:`eomatch.enrich.geometric`
- :py:mod:`eomatch.enrich.solar_elevation`
- :py:mod:`eomatch.enrich.land_fraction`

Example — from Python::

    from eomatch.mu_stac import MatchupCatalogue
    from eomatch.enrich import enrich
    from eomatch.enrich.time_diff import time_diff
    from eomatch.enrich.geometric import geometric

    catalogue = MatchupCatalogue.open("/data/my_catalogue")
    n = enrich(catalogue, enrichers=[time_diff, geometric])
    print(f"Enriched {n} matchup item(s).")

Example — from the CLI::

    eomatch-enrich \\
        --catalogue /data/my_catalogue \\
        --enricher eomatch.enrich.time_diff.time_diff \\
        --enricher eomatch.enrich.geometric.geometric \\
        --enricher my_package.my_enrichers.cloud_cover

The ``overwrite`` flag controls whether properties that already exist on an
item are replaced.  Default is ``False`` (existing values are kept).
"""

from __future__ import annotations

import argparse
import importlib
import logging
from typing import Any, Callable, Dict, Iterable, List

from eomatch.domain import Matchup, MATCHUP_EVENTS_COLLECTION_PREFIX

__all__ = ["enrich"]

log = logging.getLogger(__name__)


def enrich(
    catalogue,
    enrichers: Iterable[Callable[[Matchup], Dict[str, Any]]],
    overwrite: bool = False,
) -> int:
    """Apply *enrichers* to every matchup item in *catalogue*.

    For each matchup STAC Item the function:

    1. Reconstructs the :py:class:`~eomatch.domain.Matchup` domain object
       from the item's ``derived_from`` links.
    2. Calls every enricher with the ``Matchup`` and merges the returned dicts.
    3. Writes the new key/value pairs back to ``item.properties`` (skipping keys
       that already exist unless *overwrite* is ``True``).
    4. Saves the updated item JSON to disk (if the item has a ``self_href``).

    Enrichers that raise an exception are logged as warnings and skipped for
    that item, so a single failure does not abort the whole run.

    :param catalogue: :py:class:`~eomatch.mu_stac.MatchupCatalogue` to enrich.
    :param enrichers: iterable of enricher callables.
    :param overwrite: when ``True``, existing property values are replaced;
        when ``False`` (default), existing properties are kept unchanged.
    :return: number of matchup items enriched.
    """
    enricher_list = list(enrichers)
    prefix = f"{MATCHUP_EVENTS_COLLECTION_PREFIX}-"
    n_enriched = 0

    for col in catalogue.catalog.get_children():
        # Matchup collections contain "-vs-" and do not start with the events prefix.
        if col.id.startswith(prefix) or "-vs-" not in col.id:
            continue

        for mu_item in col.get_items():
            try:
                mu = Matchup.from_stac_item(mu_item)
            except Exception as exc:
                log.warning("Could not reconstruct Matchup from item %r: %s", mu_item.id, exc)
                continue

            new_props: Dict[str, Any] = {}
            for enricher in enricher_list:
                try:
                    result = enricher(mu)
                    new_props.update(result)
                except Exception as exc:
                    log.warning(
                        "Enricher %r failed for item %r: %s",
                        getattr(enricher, "__name__", repr(enricher)),
                        mu_item.id,
                        exc,
                    )

            if not new_props:
                continue

            changed = False
            for key, value in new_props.items():
                if overwrite or key not in mu_item.properties:
                    mu_item.properties[key] = value
                    changed = True

            if changed:
                self_href = mu_item.get_self_href()
                if self_href is not None:
                    mu_item.save_object()
                n_enriched += 1
                log.debug("Enriched item %r with keys: %s", mu_item.id, list(new_props))

    log.info("Enriched %d matchup item(s).", n_enriched)
    return n_enriched


def _load_enricher(dotted_path: str) -> Callable:
    """Import and return a callable from a dotted module path.

    :param dotted_path: fully qualified name, e.g.
        ``eomatch.enrich.time_diff.time_diff``.
    :return: the callable object.
    :raises ImportError: if the module cannot be imported.
    :raises AttributeError: if the attribute does not exist in the module.
    :raises ValueError: if the path has no module component.
    """
    module_path, _, attr = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(
            f"Enricher {dotted_path!r} must be a fully qualified dotted path, e.g. eomatch.enrich.time_diff.time_diff"
        )
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def main() -> None:
    """CLI entry point for ``eomatch-enrich``."""
    parser = argparse.ArgumentParser(
        description=(
            "Apply enrichers to every matchup item in a local STAC catalogue, "
            "writing computed properties back to the item JSON files."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--catalogue",
        metavar="PATH",
        required=True,
        help="Path to the local catalogue root directory (or catalog.json).",
    )
    parser.add_argument(
        "--enricher",
        metavar="DOTTED_PATH",
        dest="enrichers",
        action="append",
        default=[],
        help=(
            "Fully qualified dotted path to an enricher callable, e.g. "
            "eomatch.enrich.time_diff.time_diff.  "
            "Repeat to apply multiple enrichers."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing property values rather than keeping them.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="EOMatch YAML config file (optional).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.enrichers:
        parser.error("Supply at least one --enricher dotted path.")

    enricher_callables: List[Callable] = []
    for path in args.enrichers:
        try:
            enricher_callables.append(_load_enricher(path))
        except (ImportError, AttributeError, ValueError) as exc:
            parser.error(f"Could not load enricher {path!r}: {exc}")

    from eomatch.mu_stac import MatchupCatalogue

    catalogue = MatchupCatalogue.open(args.catalogue)

    enrich(catalogue, enrichers=enricher_callables, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
