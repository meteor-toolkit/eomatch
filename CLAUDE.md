# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e .          # install package and dependencies
pre-commit install         # install black formatting hook (run once after clone)

pytest                                        # run all tests
pytest eomatch/tests/test_domain.py      # run a single test file
pytest eomatch/tests/test_domain.py::TestMatchup::test_collocation_region  # run a single test
```

Linting uses `flake8` (max line length 120) and type checking uses `mypy` (with `ignore_missing_imports = True`). The pre-commit hook runs `black` on commit.

## Architecture

This package identifies and indexes Earth Observation product matchups — instances where two satellite scenes overlap in space and time — and builds collocated datasets from them.

### Domain model (`eomatch/domain.py`)

Three core classes:

- **`MatchupEvent`** — a satellite crossover opportunity, defined by platforms, collections, a time window, and a bounding box. Created from `orbitx` output. Knows how to generate `scrappi` queries for each platform.
- **`Matchup`** — a single pairwise product overlap. Wraps a `scrappi.ProductItemSet` (two or more `ProductItem` objects). Validates that product geometries intersect. Exposes `collocation_region` (shapely intersection polygon) and time-difference helpers.
- **`MatchupSet`** — ordered container of `Matchup` objects with sequence protocol.

### Discovery pipeline (`eomatch/mu_finder.py`)

`BaseMUFinder` (abstract, extends `processor_tools.BaseProcessor`) → implemented by `Sat2SatMUFinder` and `Sat2InSituMUFinder`.

`Sat2SatMUFinder.finder()` flow:
1. Calls `orbitx.return_matchups()` (or reads a cached NetCDF) → parses into `MatchupEvent` list.
2. For each event, queries `scrappi` per platform → filters for geometric overlap → creates `Matchup` objects.
3. Serialises events and matchups as JSON, returns a `MatchupSet`.

### Dataset building (`eomatch/datatree.py`)

`BuildMUDT.run(matchup)` — downloads products via `scrappi` if needed, reads each using `eoio.read()`, assembles an `xr.DataTree` with one node per sensor (`sensor_1`, `sensor_2`, …).

`Matchup.return_matchup_dataset()` is a convenience wrapper around this.

### Configuration (`eomatch/context.py`)

`Context` reads INI-style config files (via `configparser`). All runtime parameters (paths, credentials, platform lists, time ranges, thresholds) are stored here. `DEFAULT_CONFIG_PATH` points to `eomatch/etc/default_config.yaml`. Finders receive a `Context` via `processor_tools.BaseProcessor`.

### Key external dependencies

- **`scrappi`** — product catalogue query layer. `ProductItem` wraps a STAC Item; `ProductItemSet` is a collection of them.
- **`orbitx`** — satellite orbit propagation and crossover detection.
- **`eoio`** — EO data reader (used in `datatree`).
- **`processor_tools`** — provides `BaseProcessor` and `Context`.

### Current branch (`51-stac`)

Active work to migrate `Matchup` and `MatchupEvent` serialisation from custom JSON to STAC Items via `pystac`. The design uses a separate STAC catalogue with two Collections: one for matchup events (one Item per crossover) and one per matchup type (e.g. S2 vs Landsat), with `derived_from` links pointing back to the underlying `ProductItem` STAC Items and a `matchup:event_id` property linking matchup Items to their parent event Item.

### Comments

We want descriptive doc strings for all methods. arguments and return values should be described in the sphinx style (e.g., :param x:) - these don't need to include types as they should be defined in the type annotations. Class doc strings should include code snippets where reasonable.

### Logging

Log with the logger library