"""eomatch.tests.test_query — tests for eomatch.query"""

import datetime as dt
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pystac
import pystac.layout

from eomatch.query import (
    _collect_missing_ids,
    _item_id_from_href,
    _rewrite_cross_item_links,
    query,
)

__all__ = []

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NONE_INTERVAL: list[list[dt.datetime | None]] = [[None, None]]
_EXTENT = pystac.Extent(
    spatial=pystac.SpatialExtent(bboxes=[[-180.0, -90.0, 180.0, 90.0]]),
    temporal=pystac.TemporalExtent(intervals=_NONE_INTERVAL),
)


def _make_collection(col_id: str) -> pystac.Collection:
    return pystac.Collection(id=col_id, description=col_id, extent=_EXTENT)


def _make_item(item_id: str, collection_id: str, datetime=None) -> pystac.Item:
    return pystac.Item(
        id=item_id,
        geometry={"type": "Point", "coordinates": [0, 0]},
        bbox=[-1, -1, 1, 1],
        datetime=datetime or dt.datetime(2022, 5, 21, tzinfo=dt.timezone.utc),
        properties={},
        collection=collection_id,
    )


def _make_catalogue_with_items(*collections_and_items):
    """Build an in-memory catalogue. Pass (collection_id, [item, ...]) pairs."""
    cat = pystac.Catalog(id="test-cat", description="test")
    for col_id, items in collections_and_items:
        col = _make_collection(col_id)
        cat.add_child(col)
        for item in items:
            col.add_item(item)
    return cat


def _normalize(cat: pystac.Catalog, tmpdir: str) -> None:
    strategy = pystac.layout.TemplateLayoutStrategy(item_template="${year}/${month}/${day}/${id}.json")
    cat.normalize_hrefs(tmpdir, strategy=strategy)


# ---------------------------------------------------------------------------
# _item_id_from_href
# ---------------------------------------------------------------------------


class TestItemIdFromHref(unittest.TestCase):
    def test_relative_path_with_json(self):
        self.assertEqual(
            _item_id_from_href("../../../events/2022/5/21/my-event.json"),
            "my-event",
        )

    def test_relative_path_without_json(self):
        self.assertEqual(_item_id_from_href("../events/my-event"), "my-event")

    def test_http_url_with_json(self):
        self.assertEqual(
            _item_id_from_href("http://localhost:8000/LANDSAT/2022/05/21/matchup-001.json"),
            "matchup-001",
        )

    def test_api_items_url(self):
        self.assertEqual(
            _item_id_from_href("http://localhost:8000/api/collections/LANDSAT/items/matchup-001"),
            "matchup-001",
        )

    def test_broken_http_url(self):
        # URL produced by resolving a relative path against an API self-href
        self.assertEqual(
            _item_id_from_href("http://localhost:8000/external/LANDSAT/2022/05/21/matchup-001.json"),
            "matchup-001",
        )

    def test_empty_string_returns_none(self):
        self.assertIsNone(_item_id_from_href(""))

    def test_none_returns_none(self):
        self.assertIsNone(_item_id_from_href(None))

    def test_trailing_slash_stripped(self):
        self.assertEqual(_item_id_from_href("items/my-item/"), "my-item")

    def test_id_with_underscores_and_hyphens(self):
        self.assertEqual(
            _item_id_from_href("LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A_20220521T000000_20220521T084640.json"),
            "LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A_20220521T000000_20220521T084640",
        )


# ---------------------------------------------------------------------------
# _collect_missing_ids
# ---------------------------------------------------------------------------


class TestCollectMissingIds(unittest.TestCase):
    def _cat_with_event_linking_to(self, target_href: str) -> pystac.Catalog:
        event = _make_item("event-001", "events")
        event.add_link(
            pystac.Link(
                "related",
                target_href,
                extra_fields={"matchup:role": "matchup"},
            )
        )
        return _make_catalogue_with_items(("events", [event]))

    def test_missing_id_found_via_relative_href(self):
        cat = self._cat_with_event_linking_to("../../../../matchups/2022/5/21/mu-001.json")
        missing = _collect_missing_ids(cat, {"event-001"})
        self.assertEqual(missing, {"mu-001"})

    def test_missing_id_found_via_http_url(self):
        cat = self._cat_with_event_linking_to("http://localhost:8000/LANDSAT/2022/05/21/mu-001.json")
        missing = _collect_missing_ids(cat, {"event-001"})
        self.assertEqual(missing, {"mu-001"})

    def test_known_id_not_returned(self):
        cat = self._cat_with_event_linking_to("../../../../matchups/2022/5/21/mu-001.json")
        missing = _collect_missing_ids(cat, {"event-001", "mu-001"})
        self.assertEqual(missing, set())

    def test_resolved_target_item_used_directly(self):
        mu = _make_item("mu-001", "matchups")
        event = _make_item("event-001", "events")
        # Link whose .target is a resolved pystac.Item (no href needed)
        event.add_link(pystac.Link("related", mu))
        cat = _make_catalogue_with_items(("events", [event]))
        missing = _collect_missing_ids(cat, {"event-001"})
        self.assertEqual(missing, {"mu-001"})

    def test_ignores_non_cross_item_links(self):
        event = _make_item("event-001", "events")
        event.add_link(pystac.Link("self", "http://api/items/event-001"))
        event.add_link(pystac.Link("root", "../../../catalog.json"))
        cat = _make_catalogue_with_items(("events", [event]))
        missing = _collect_missing_ids(cat, {"event-001"})
        self.assertEqual(missing, set())

    def test_derived_from_links_included(self):
        mu = _make_item("mu-001", "matchups")
        mu.add_link(pystac.Link("derived_from", "../../../../LANDSAT/2022/5/21/product-001.json"))
        cat = _make_catalogue_with_items(("matchups", [mu]))
        missing = _collect_missing_ids(cat, {"mu-001"})
        self.assertEqual(missing, {"product-001"})

    def test_cascade_two_levels(self):
        # event → mu-001 → product-001 — collect all missing from empty known set
        event = _make_item("event-001", "events")
        event.add_link(pystac.Link("related", "../../../../matchups/2022/5/21/mu-001.json"))
        mu = _make_item("mu-001", "matchups")
        mu.add_link(pystac.Link("derived_from", "../../../../products/2022/5/21/product-001.json"))
        cat = _make_catalogue_with_items(
            ("events", [event]),
            ("matchups", [mu]),
        )
        # First pass: from event's known set → mu-001 missing
        pass1 = _collect_missing_ids(cat, {"event-001"})
        self.assertIn("mu-001", pass1)
        # Second pass: after adding mu-001 → product-001 missing
        pass2 = _collect_missing_ids(cat, {"event-001", "mu-001"})
        self.assertIn("product-001", pass2)


# ---------------------------------------------------------------------------
# _rewrite_cross_item_links
# ---------------------------------------------------------------------------


class TestRewriteCrossItemLinks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _build_and_normalize(self, *collections_and_items):
        cat = _make_catalogue_with_items(*collections_and_items)
        _normalize(cat, self.tmpdir)
        return cat

    def test_relative_link_rewritten_to_correct_path(self):
        event = _make_item("event-001", "events")
        event.add_link(
            pystac.Link(
                "related",
                "../../../../matchups/2022/05/21/mu-001.json",
                extra_fields={"matchup:role": "matchup"},
            )
        )
        mu = _make_item("mu-001", "matchups")
        cat = self._build_and_normalize(
            ("events", [event]),
            ("matchups", [mu]),
        )
        _rewrite_cross_item_links(cat)

        link = next(lnk for lnk in event.links if lnk.rel == "related")
        expected = os.path.relpath(mu.get_self_href(), os.path.dirname(event.get_self_href()))
        self.assertEqual(link.target, expected)

    def test_http_url_rewritten_to_local_path(self):
        event = _make_item("event-001", "events")
        event.add_link(
            pystac.Link(
                "related",
                "http://localhost:8000/matchups/2022/05/21/mu-001.json",
            )
        )
        mu = _make_item("mu-001", "matchups")
        cat = self._build_and_normalize(
            ("events", [event]),
            ("matchups", [mu]),
        )
        _rewrite_cross_item_links(cat)

        link = next(lnk for lnk in event.links if lnk.rel == "related")
        self.assertFalse(link.target.startswith("http"))
        self.assertTrue(link.target.endswith("mu-001.json"))

    def test_link_to_absent_item_left_unchanged(self):
        event = _make_item("event-001", "events")
        original_href = "../../../../matchups/2022/05/21/missing.json"
        event.add_link(pystac.Link("related", original_href))
        cat = self._build_and_normalize(("events", [event]))
        _rewrite_cross_item_links(cat)

        link = next(lnk for lnk in event.links if lnk.rel == "related")
        self.assertEqual(link.target, original_href)

    def test_resolved_item_target_rewritten(self):
        mu = _make_item("mu-001", "matchups")
        event = _make_item("event-001", "events")
        event.add_link(pystac.Link("related", mu))
        cat = self._build_and_normalize(
            ("events", [event]),
            ("matchups", [mu]),
        )
        _rewrite_cross_item_links(cat)

        link = next(lnk for lnk in event.links if lnk.rel == "related")
        # After rewrite the target should be a relative string, not a pystac.Item
        self.assertIsInstance(link.target, str)

    def test_saved_link_resolves_to_existing_file(self):
        event = _make_item("event-001", "events")
        event.add_link(pystac.Link("related", "../../../../matchups/2022/05/21/mu-001.json"))
        mu = _make_item("mu-001", "matchups")
        cat = self._build_and_normalize(
            ("events", [event]),
            ("matchups", [mu]),
        )
        _rewrite_cross_item_links(cat)
        cat.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)

        # Load the saved event and verify the related href resolves to a real file
        saved_paths = [
            os.path.join(r, f) for r, _, files in os.walk(self.tmpdir) for f in files if f == "event-001.json"
        ]
        self.assertTrue(saved_paths, "event-001.json not found after save")
        with open(saved_paths[0]) as fp:
            saved = json.load(fp)

        related_hrefs = [lnk["href"] for lnk in saved["links"] if lnk["rel"] == "related"]
        self.assertTrue(related_hrefs, "no related link in saved item")
        resolved = os.path.normpath(os.path.join(os.path.dirname(saved_paths[0]), related_hrefs[0]))
        self.assertTrue(os.path.exists(resolved), f"resolved path does not exist: {resolved}")

    def test_non_cross_item_links_untouched(self):
        event = _make_item("event-001", "events")
        cat = self._build_and_normalize(("events", [event]))
        original_links = {(lnk.rel, lnk.target) for lnk in event.links if lnk.rel not in ("related", "derived_from")}
        _rewrite_cross_item_links(cat)
        after_links = {(lnk.rel, lnk.target) for lnk in event.links if lnk.rel not in ("related", "derived_from")}
        self.assertEqual(original_links, after_links)


# ---------------------------------------------------------------------------
# query() — integration tests with a mocked pystac_client
# ---------------------------------------------------------------------------


def _item_dict(item_id: str, collection_id: str, links=None) -> dict:
    """Build a minimal STAC item dict as returned by items_as_dicts()."""
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "collection": collection_id,
        "geometry": {"type": "Point", "coordinates": [0, 0]},
        "bbox": [-1, -1, 1, 1],
        "properties": {"datetime": "2022-05-21T08:35:05Z"},
        "assets": {},
        "links": links
        or [
            {
                "rel": "self",
                "href": f"http://localhost:8000/external/collections/{collection_id}/items/{item_id}",
            }
        ],
    }


class TestQuery(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _run_query(self, items_by_search, **kwargs):
        """Patch pystac_client and run query(). items_by_search maps search
        kwargs tuples to lists of item dicts returned by items_as_dicts()."""
        call_count = [0]

        def search_side_effect(**search_kwargs):
            call_count[0] += 1
            result = MagicMock()
            # Match by 'ids' kwarg for the iterative fetch calls
            ids = frozenset(search_kwargs.get("ids", []))
            for key, item_dicts in items_by_search.items():
                if ids and ids <= set(key):
                    result.items_as_dicts.return_value = iter(item_dicts)
                    return result
            # Default: return items for any key that isn't ids-based
            for key, item_dicts in items_by_search.items():
                if not ids:
                    result.items_as_dicts.return_value = iter(item_dicts)
                    return result
            result.items_as_dicts.return_value = iter([])
            return result

        mock_client = MagicMock()
        mock_client.search.side_effect = search_side_effect

        with patch("pystac_client.Client") as MockClient:
            MockClient.open.return_value = mock_client
            cat = query(
                api_url="http://localhost:8000/external/",
                output_path=self.tmpdir,
                **kwargs,
            )
        return cat, mock_client

    def test_fetched_items_appear_in_catalogue(self):
        event_dict = _item_dict("event-001", "matchup-events-LANDSAT")
        items_by_search = {("initial",): [event_dict]}

        cat, _ = self._run_query(items_by_search)

        ids = {item.id for item in cat.get_items(recursive=True)}
        self.assertIn("event-001", ids)

    def test_catalogue_saved_to_disk(self):
        event_dict = _item_dict("event-001", "matchup-events-LANDSAT")
        items_by_search = {("initial",): [event_dict]}

        self._run_query(items_by_search)

        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "catalog.json")))

    def test_no_colon_in_saved_filenames(self):
        event_dict = _item_dict("event-20220521T083505", "matchup-events-LANDSAT")
        items_by_search = {("initial",): [event_dict]}

        self._run_query(items_by_search)

        for root, dirs, files in os.walk(self.tmpdir):
            for name in files + dirs:
                self.assertNotIn(":", name, f"colon in path component: {name}")

    def test_upsert_replaces_existing_item(self):
        event_dict = _item_dict("event-001", "matchup-events-LANDSAT")
        items_by_search = {("initial",): [event_dict]}

        # First run
        self._run_query(items_by_search)
        # Second run — same item, should not duplicate
        cat2, _ = self._run_query(items_by_search)

        ids = [item.id for item in cat2.get_items(recursive=True)]
        self.assertEqual(ids.count("event-001"), 1)

    def test_referenced_items_fetched_iteratively(self):
        mu_id = "mu-001"
        event_dict = _item_dict(
            "event-001",
            "matchup-events-LANDSAT",
            links=[
                {
                    "rel": "self",
                    "href": "http://localhost:8000/external/collections/matchup-events-LANDSAT/items/event-001",
                },
                {
                    "rel": "related",
                    "href": f"../../../../LANDSAT/2022/5/21/{mu_id}.json",
                    "matchup:role": "matchup",
                },
            ],
        )
        mu_dict = _item_dict(mu_id, "LANDSAT")

        # initial search returns only the event; ids-based search returns the matchup
        items_by_search = {
            ("initial",): [event_dict],
            (mu_id,): [mu_dict],
        }

        cat, mock_client = self._run_query(items_by_search)

        ids = {item.id for item in cat.get_items(recursive=True)}
        self.assertIn("event-001", ids)
        self.assertIn(mu_id, ids)
        # The iterative search was called at least once
        self.assertGreater(mock_client.search.call_count, 1)

    def test_cross_item_links_resolve_locally_after_save(self):
        mu_id = "mu-001"
        event_dict = _item_dict(
            "event-001",
            "matchup-events-LANDSAT",
            links=[
                {
                    "rel": "self",
                    "href": "http://localhost:8000/external/collections/matchup-events-LANDSAT/items/event-001",
                },
                {
                    "rel": "related",
                    "href": f"../../../../LANDSAT/2022/5/21/{mu_id}.json",
                    "matchup:role": "matchup",
                },
            ],
        )
        mu_dict = _item_dict(mu_id, "LANDSAT")

        items_by_search = {
            ("initial",): [event_dict],
            (mu_id,): [mu_dict],
        }

        self._run_query(items_by_search)

        # Find the saved event item
        event_files = [
            os.path.join(r, f) for r, _, files in os.walk(self.tmpdir) for f in files if f == "event-001.json"
        ]
        self.assertTrue(event_files)
        with open(event_files[0]) as fp:
            saved = json.load(fp)

        related = [lnk for lnk in saved["links"] if lnk["rel"] == "related"]
        self.assertTrue(related, "no related link in saved event item")
        resolved = os.path.normpath(os.path.join(os.path.dirname(event_files[0]), related[0]["href"]))
        self.assertTrue(
            os.path.exists(resolved),
            f"related link does not resolve to an existing file: {resolved}",
        )

    def test_missing_api_items_logs_warning_and_continues(self):
        event_dict = _item_dict(
            "event-001",
            "matchup-events-LANDSAT",
            links=[
                {
                    "rel": "self",
                    "href": "http://localhost:8000/external/collections/matchup-events-LANDSAT/items/event-001",
                },
                {"rel": "related", "href": "../../../../LANDSAT/2022/5/21/ghost.json"},
            ],
        )
        # The API has no item for "ghost"
        items_by_search = {("initial",): [event_dict], ("ghost",): []}

        with self.assertLogs("eomatch.query", level="WARNING") as cm:
            cat, _ = self._run_query(items_by_search)

        self.assertTrue(any("ghost" in msg or "referenced" in msg for msg in cm.output))
        # The event itself was still saved
        ids = {item.id for item in cat.get_items(recursive=True)}
        self.assertIn("event-001", ids)


if __name__ == "__main__":
    unittest.main()
