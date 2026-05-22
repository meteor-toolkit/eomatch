"""eomatch.deps — lazy imports for optional dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import geopandas  # noqa: F401


def _require_extra(extra: str, import_name: str) -> None:
    raise ModuleNotFoundError(
        f"Optional dependency '{import_name}' is required for this operation. "
        f"Install with: pip install 'eomatch[{extra}]'"
    )


def lazy_geopandas():
    """Import and return geopandas, applying the PROJ database workaround first.

    On macOS with conda-installed pyproj (PROJ 9.7+) the bundled ``proj.db`` may
    not be reachable when pyproj's ``network.py`` initialises, causing a
    ``CRSError`` when geopandas later tries to parse any CRS string.  This
    function probes the conda prefix for a working ``proj.db`` and calls
    ``pyproj.datadir.set_data_dir`` before importing geopandas, mirroring the
    pattern in ``eoio.deps.lazy_pyproj``.

    :return: the ``geopandas`` module.
    :raises ModuleNotFoundError: if geopandas is not installed.
    """
    import os
    import sys

    # Linux/macOS conda: <prefix>/share/proj; Windows conda: <prefix>/Library/share/proj
    _candidates = [
        os.path.join(sys.prefix, "share", "proj"),
        os.path.join(sys.prefix, "Library", "share", "proj"),
    ]
    proj_data = next(
        (c for c in _candidates if os.path.exists(os.path.join(c, "proj.db"))),
        os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB"),
    )
    if proj_data:
        os.environ.setdefault("PROJ_DATA", proj_data)
        try:
            import pyproj  # type: ignore

            pyproj.datadir.set_data_dir(proj_data)
        except Exception:
            pass

    try:
        import geopandas  # type: ignore
    except ModuleNotFoundError:
        _require_extra("enrich", "geopandas")

    return geopandas
