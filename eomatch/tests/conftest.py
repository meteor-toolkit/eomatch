"""eomatch.tests.conftest - pytest configuration for the test suite."""

import sys
import types
from typing import Optional


# s2_rut_python is an optional eoio dependency that is not present in all
# environments. Stub it out before any test module is imported so that the
# eoio import chain does not fail during collection.
def _stub_module(full_name: str, attrs: Optional[dict] = None):
    parts = full_name.split(".")
    for i in range(1, len(parts) + 1):
        name = ".".join(parts[:i])
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
    if attrs:
        for k, v in attrs.items():
            setattr(sys.modules[full_name], k, v)


if "s2_rut_python" not in sys.modules:
    _stub_module("s2_rut_python")
    _stub_module("s2_rut_python.interface", {"S2RUTTool": object})
