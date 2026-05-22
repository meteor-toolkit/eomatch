# eomatch

Match up dataset generation for Earth Observation satellites.

`eomatch` identifies and indexes instances where two satellite scenes overlap
in space and time, builds collocated datasets from them, and manages the
results as versioned STAC catalogues.

> **Warning:** This software is in beta. Results should be used with
> caution. Please share any feedback via the issue tracker.

## Usage

### Virtual environment

It is always recommended to use a virtual environment for each Python project.
Use your preferred environment manager, or create one with:

```bash
python -m venv venv
```

Activate it on Windows with `venv\Scripts\activate`, or on macOS/Linux with
`source venv/bin/activate`.

### Installation

Install the package and its core dependencies:

```bash
pip install -e .
```

Optional extras are available depending on your use case:

```bash
pip install -e ".[ingest]"   # pgSTAC database ingestion (pypgstac)
pip install -e ".[query]"    # STAC API querying (pystac-client)
pip install -e ".[enrich]"   # Geometric and solar-angle enrichment
pip install -e ".[dev]"      # Development tools (ruff, mypy, pytest, …)
pip install -e ".[docs]"     # Documentation build (sphinx, …)
```

To install all extras at once:

```bash
pip install -e ".[ingest,query,enrich,dev,docs]"
```

### Development

Install the pre-commit hooks after cloning:

```bash
pre-commit install
```

When you commit, `ruff` will lint and format your code. If it makes
corrections the commit will be aborted so you can review the changes — just
commit again once you are happy.

Run the test suite with:

```bash
pytest
```

## Compatibility

`eomatch` requires Python 3.11 or later and is tested on Python 3.11, 3.12,
and 3.13.

## Licence

`eomatch` is released under the GNU Lesser General Public License v3 (LGPLv3).
See the [LICENSE](https://github.com/meteor-toolkit/eomatch/blob/main/LICENSE) file for the full licence text.

## Authors

`eomatch` is developed and maintained by the
[MetEOR Toolkit Team](mailto:team@comet-toolkit.org).
