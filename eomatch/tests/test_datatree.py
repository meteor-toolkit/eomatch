"""eomatch.tests.test_datatree - tests for eomatch.datatree"""

import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import xarray as xr
from eomatch.datatree import (
    BuildMUDT,
    _FALLBACK_VARS_SEL,
    _FALLBACK_READ_PARAMS,
    _FALLBACK_PROCESSORS,
)

__author__ = "Sam Hunt <sam.hunt@npl.co.uk>"


def create_test_product_ds():
    r1a = np.ones((4, 3)) * 1
    r1a_attrs = {"units": "test_units", "geometry": "a", "measurand": "r"}
    r1b = np.ones((10, 5)) * 1
    r1b_attrs = {"units": "test_units", "geometry": "b", "measurand": "r"}

    ds1 = xr.Dataset(
        {
            "r_a": (["x_a", "y_a"], r1a, r1a_attrs),
            "r_b": (["x_b", "y_b"], r1b, r1b_attrs),
        },
        attrs={
            "history": "test_history1",
            "meas_vars": ["r_a", "r_b"],
            "collection": "SENSOR_1",
        },
    )

    r2 = np.ones((10, 5)) * 1
    r2_attrs = {"units": "test_units", "geometry": "b", "measurand": "r"}

    ds2 = xr.Dataset(
        {
            "r": (["x", "y"], r2, r2_attrs),
        },
        attrs={
            "history": "test_history2",
            "meas_vars": ["r"],
            "collection": "SENSOR_2",
        },
    )

    return [ds1, ds2]


def mock_os_path_exists(path):
    if path == "path_a":
        return True
    return False


class TestBuildMUDT(unittest.TestCase):
    @patch("eomatch.datatree.BuildMUDT.read_products", return_value="product_ds")
    @patch("eomatch.datatree.BuildMUDT.to_datatree")
    def test_run_calls_read_and_to_datatree(self, mock_to_dt, mock_read):
        mock_matchup = MagicMock()

        bmudt = BuildMUDT()
        result = bmudt.run(mock_matchup)

        mock_read.assert_called_once_with(
            mock_matchup.products,
            mock_matchup.collocation_region,
            collection_read_args=None,
        )
        mock_to_dt.assert_called_once_with(mock_read.return_value)
        self.assertEqual(result, mock_to_dt.return_value)

    def test_to_datatree_nodes_named_by_collection(self):
        product_ds = create_test_product_ds()

        bmudt = BuildMUDT()
        mudt = bmudt.to_datatree(product_ds)

        self.assertIn("SENSOR_1", mudt.children)
        self.assertIn("SENSOR_2", mudt.children)

    def test_to_datatree_variables_unchanged(self):
        product_ds = create_test_product_ds()

        bmudt = BuildMUDT()
        mudt = bmudt.to_datatree(product_ds)

        self.assertIn("r_a", mudt["SENSOR_1"].ds.data_vars)
        self.assertIn("r_b", mudt["SENSOR_1"].ds.data_vars)
        self.assertIn("r", mudt["SENSOR_2"].ds.data_vars)

    def test_to_datatree_duplicate_collection_suffixed(self):
        product_ds = create_test_product_ds()
        product_ds.append(product_ds[0].copy())

        bmudt = BuildMUDT()
        mudt = bmudt.to_datatree(product_ds)

        self.assertIn("SENSOR_1", mudt.children)
        self.assertIn("SENSOR_1_2", mudt.children)

    def test_to_datatree_has_date_created_attr(self):
        product_ds = create_test_product_ds()

        bmudt = BuildMUDT()
        mudt = bmudt.to_datatree(product_ds)

        self.assertIn("date_created", mudt.attrs)


class TestResolveReadKwargs(unittest.TestCase):
    """Tests for BuildMUDT._resolve_read_kwargs merge logic."""

    def _make_builder(self, read_cfg=None):
        """Return a BuildMUDT whose context.get('read') returns ``read_cfg``."""
        builder = BuildMUDT.__new__(BuildMUDT)
        mock_ctx = MagicMock()
        mock_ctx.get.return_value = read_cfg
        builder.context = mock_ctx
        return builder

    def test_no_config_no_overrides_returns_fallbacks(self):
        b = self._make_builder(read_cfg=None)
        vs, rp, pr = b._resolve_read_kwargs("ANY", None)
        self.assertEqual(vs, _FALLBACK_VARS_SEL)
        self.assertEqual(rp, _FALLBACK_READ_PARAMS)
        self.assertEqual(pr, _FALLBACK_PROCESSORS)

    def test_global_defaults_applied(self):
        b = self._make_builder({"defaults": {"vars_sel": {"meas": ["B1", "B2"], "aux": []}}})
        vs, rp, pr = b._resolve_read_kwargs("ANY", None)
        self.assertEqual(vs["meas"], ["B1", "B2"])

    def test_collection_config_merges_on_top_of_global(self):
        b = self._make_builder(
            {
                "defaults": {"vars_sel": {"meas": ["B1"], "aux": ["ANG"]}},
                "collections": {"LANDSAT_C2L1": {"vars_sel": {"meas": ["B2", "B3"]}}},
            }
        )
        vs, rp, pr = b._resolve_read_kwargs("LANDSAT_C2L1", None)
        # collection overrides meas; aux survives from global defaults
        self.assertEqual(vs, {"meas": ["B2", "B3"], "aux": ["ANG"]})

    def test_unknown_collection_falls_back_to_global_defaults(self):
        b = self._make_builder(
            {
                "defaults": {"vars_sel": {"meas": ["B1"], "aux": []}},
                "collections": {"LANDSAT_C2L1": {"vars_sel": {"meas": ["B2"]}}},
            }
        )
        vs, rp, pr = b._resolve_read_kwargs("S2_MSI_L1C", None)
        self.assertEqual(vs["meas"], ["B1"])

    def test_collection_read_params_merged_on_top_of_global(self):
        b = self._make_builder(
            {
                "defaults": {"read_params": {"use_chunks": False, "metadata_level": True}},
                "collections": {"S2_MSI_L1C": {"read_params": {"metadata_level": False}}},
            }
        )
        vs, rp, pr = b._resolve_read_kwargs("S2_MSI_L1C", None)
        self.assertFalse(rp["metadata_level"])  # overridden by collection config
        self.assertFalse(rp["use_chunks"])  # global default survives

    # --- collection_read_args (call-time) ---

    def test_call_time_vars_sel_is_full_replacement(self):
        b = self._make_builder(
            {
                "defaults": {"vars_sel": {"meas": ["B1"], "aux": ["ANG"]}},
            }
        )
        vs, rp, pr = b._resolve_read_kwargs("ANY", {"ANY": {"vars_sel": {"meas": ["B4"]}}})
        # aux absent — full replacement, not sub-key merge
        self.assertEqual(vs, {"meas": ["B4"]})
        self.assertNotIn("aux", vs)

    def test_call_time_read_params_is_subkey_merge(self):
        b = self._make_builder(None)
        vs, rp, pr = b._resolve_read_kwargs("ANY", {"ANY": {"read_params": {"use_chunks": True}}})
        self.assertTrue(rp["use_chunks"])
        self.assertTrue(rp["metadata_level"])  # fallback survives
        self.assertFalse(rp["save_extracted"])  # fallback survives

    def test_call_time_read_params_adds_new_key(self):
        b = self._make_builder(None)
        vs, rp, pr = b._resolve_read_kwargs("ANY", {"ANY": {"read_params": {"custom_key": "val"}}})
        self.assertEqual(rp["custom_key"], "val")
        self.assertFalse(rp["use_chunks"])  # fallback still present

    def test_call_time_processors_is_full_replacement(self):
        b = self._make_builder(
            {
                "defaults": {"processors": {"p1": {"param": 1}}},
            }
        )
        vs, rp, pr = b._resolve_read_kwargs("ANY", {"ANY": {"processors": {"p2": {"param": 2}}}})
        self.assertEqual(pr, {"p2": {"param": 2}})
        self.assertNotIn("p1", pr)  # config processor replaced

    def test_config_processors_used_when_no_call_time_override(self):
        b = self._make_builder(
            {
                "defaults": {"processors": {"p1": {"param": 1}}},
            }
        )
        vs, rp, pr = b._resolve_read_kwargs("ANY", None)
        self.assertEqual(pr, {"p1": {"param": 1}})

    def test_call_time_override_only_applies_to_named_collection(self):
        b = self._make_builder(
            {
                "defaults": {"vars_sel": {"meas": ["B1"], "aux": []}},
            }
        )
        collection_read_args = {
            "S2_MSI_L1C": {"vars_sel": {"meas": ["B02", "B03"]}},
        }
        vs_s2, _, _ = b._resolve_read_kwargs("S2_MSI_L1C", collection_read_args)
        vs_ls, _, _ = b._resolve_read_kwargs("LANDSAT_C2L1", collection_read_args)
        self.assertEqual(vs_s2["meas"], ["B02", "B03"])  # override applied
        self.assertEqual(vs_ls["meas"], ["B1"])  # global default unchanged

    def test_all_three_call_time_keys_together(self):
        b = self._make_builder(
            {
                "defaults": {
                    "vars_sel": {"meas": ["B1"], "aux": []},
                    "read_params": {
                        "use_chunks": False,
                        "metadata_level": True,
                        "save_extracted": False,
                    },
                    "processors": {"p1": {}},
                },
            }
        )
        vs, rp, pr = b._resolve_read_kwargs(
            "ANY",
            {
                "ANY": {
                    "vars_sel": {"meas": ["B4", "B5"]},
                    "read_params": {"save_extracted": True},
                    "processors": {"p2": {}},
                }
            },
        )
        self.assertEqual(vs, {"meas": ["B4", "B5"]})  # full replace; aux gone
        self.assertTrue(rp["save_extracted"])  # overridden
        self.assertFalse(rp["use_chunks"])  # fallback survives
        self.assertEqual(pr, {"p2": {}})  # full replace; p1 gone


if __name__ == "__main__":
    unittest.main()
