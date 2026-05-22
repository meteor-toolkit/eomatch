"""eomatch.tests.test_status - tests for eomatch-status"""

from __future__ import annotations

import io
import json
import sys
import unittest
from unittest.mock import MagicMock, patch

from eomatch.status import _collection_stats, status

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"
__all__ = []

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(data: dict, status: int = 200):
    body = json.dumps(data).encode()
    mock = MagicMock()
    mock.read.return_value = body
    mock.status = status
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


_COLLECTIONS_RESP = {
    "collections": [
        {"id": "LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A"},
        {"id": "matchup-events-LANDSAT_C2L1-Landsat9-vs-S2_MSI_L1C-S2A"},
    ]
}

_SEARCH_NEWEST = {
    "type": "FeatureCollection",
    "context": {"matched": 42, "returned": 1},
    "features": [{"properties": {"datetime": "2026-05-10T12:00:00Z"}}],
}

_SEARCH_OLDEST = {
    "type": "FeatureCollection",
    "context": {"matched": 42, "returned": 1},
    "features": [{"properties": {"datetime": "2022-01-01T00:00:00Z"}}],
}

_SEARCH_EMPTY = {
    "type": "FeatureCollection",
    "context": {"matched": 0, "returned": 0},
    "features": [],
}


class TestCollectionStats(unittest.TestCase):
    def _urlopen(self, url, **kwargs):
        if "asc" in str(getattr(kwargs.get("data") or b"", "decode", lambda e="": b"")()) or b'"asc"' in (
            kwargs.get("data") or b""
        ):
            return _make_response(_SEARCH_OLDEST)
        return _make_response(_SEARCH_NEWEST)

    @patch("eomatch.status.urllib.request.urlopen")
    def test_returns_count_from_context(self, mock_urlopen):
        mock_urlopen.side_effect = lambda req, **kw: (
            _make_response(_SEARCH_OLDEST) if b'"asc"' in (req.data or b"") else _make_response(_SEARCH_NEWEST)
        )
        count, newest, oldest = _collection_stats("http://server/api", "col-1")
        self.assertEqual(count, 42)

    @patch("eomatch.status.urllib.request.urlopen")
    def test_returns_newest_datetime(self, mock_urlopen):
        mock_urlopen.side_effect = lambda req, **kw: (
            _make_response(_SEARCH_OLDEST) if b'"asc"' in (req.data or b"") else _make_response(_SEARCH_NEWEST)
        )
        _, newest, _ = _collection_stats("http://server/api", "col-1")
        self.assertEqual(newest, "2026-05-10T12:00:00Z")

    @patch("eomatch.status.urllib.request.urlopen")
    def test_returns_oldest_datetime(self, mock_urlopen):
        mock_urlopen.side_effect = lambda req, **kw: (
            _make_response(_SEARCH_OLDEST) if b'"asc"' in (req.data or b"") else _make_response(_SEARCH_NEWEST)
        )
        _, _, oldest = _collection_stats("http://server/api", "col-1")
        self.assertEqual(oldest, "2022-01-01T00:00:00Z")

    @patch("eomatch.status.urllib.request.urlopen")
    def test_empty_collection_returns_none_datetime(self, mock_urlopen):
        mock_urlopen.return_value = _make_response(_SEARCH_EMPTY)
        count, newest, oldest = _collection_stats("http://server/api", "empty-col")
        self.assertIsNone(newest)
        self.assertIsNone(oldest)
        self.assertEqual(count, 0)

    @patch("eomatch.status.urllib.request.urlopen")
    def test_network_error_returns_nones(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        count, newest, oldest = _collection_stats("http://server/api", "col-1")
        self.assertIsNone(count)
        self.assertIsNone(newest)
        self.assertIsNone(oldest)


class TestStatus(unittest.TestCase):
    @patch("eomatch.status.urllib.request.urlopen")
    def test_prints_table(self, mock_urlopen):
        def _side_effect(req, **kw):
            url = req if isinstance(req, str) else req.full_url
            if "collections" in url and not hasattr(req, "data"):
                return _make_response(_COLLECTIONS_RESP)
            data = req.data if hasattr(req, "data") else b""
            if b'"asc"' in (data or b""):
                return _make_response(_SEARCH_OLDEST)
            return _make_response(_SEARCH_NEWEST)

        mock_urlopen.side_effect = _side_effect

        captured = io.StringIO()
        sys.stdout = captured
        try:
            status("http://server:8000/api/")
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        self.assertIn("LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A", output)
        self.assertIn("42", output)
        self.assertIn("2026-05-10", output)

    @patch("eomatch.status.urllib.request.urlopen")
    def test_unreachable_api_prints_error(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        captured = io.StringIO()
        sys.stdout = captured
        try:
            status("http://server:8000/api/")
        finally:
            sys.stdout = sys.__stdout__

        self.assertIn("ERROR", captured.getvalue())

    @patch("eomatch.status.urllib.request.urlopen")
    def test_trailing_slash_stripped(self, mock_urlopen):
        mock_urlopen.side_effect = lambda req, **kw: (
            _make_response(_COLLECTIONS_RESP)
            if "collections" in (req if isinstance(req, str) else req.full_url)
            else _make_response(_SEARCH_NEWEST)
        )

        captured = io.StringIO()
        sys.stdout = captured
        try:
            status("http://server:8000/api/")
        finally:
            sys.stdout = sys.__stdout__

        # Should not double-slash in any URL call
        for call in mock_urlopen.call_args_list:
            url = call[0][0]
            url_str = url if isinstance(url, str) else url.full_url
            self.assertNotIn("//collections", url_str)


if __name__ == "__main__":
    unittest.main()
