# EOMatch API & Database Architecture

## Overview

This document describes the design for serving the eomatch catalogue as a
production-grade STAC API with a web-based browser UI. The current file-based
pystac catalogue works well for local use and pipeline development, but cannot
support concurrent queries, stakeholder-facing exploration, or shared access at
scale. This design adds a database-backed API layer on top of the existing
pipeline without replacing it.

---

## Goals

- Serve the eomatch catalogue via a standard STAC API for programmatic access
- Provide a STAC Browser UI for non-technical stakeholders to explore matchups
- Allow multiple users and teams to contribute to and query a shared central catalogue
- Store analysis results (comparison NetCDFs) as versioned STAC item assets
- Deploy on-prem first, with a clear path to cloud migration later

---

## System Components

### Infrastructure

| Component | Role |
|-----------|------|
| **PostgreSQL + pgSTAC** | Database backing the STAC catalogue. pgSTAC provides spatial/temporal indexes and is designed to handle hundreds of millions of items. |
| **stac-fastapi** (×2) | Python STAC API server. Two instances point at the same database: one internal (full access), one external (filtered). |
| **STAC Browser** | Static Vue.js web app (Radiant Earth). Points at the external stac-fastapi URL. No server-side code. |
| **nginx** | Reverse proxy. Handles API-key authentication for write endpoints, routes internal vs external traffic. |
| **NFS** | Shared network drive mounted on the server and on researcher workstations. Stores downloaded EO products and analysis NetCDFs. |

### Docker Compose stack

All services run in a single Compose file for straightforward on-prem deployment.
The stack is identical whether hosted on an NPL server or a cloud VM.

```
┌─────────────────────────────────────────────────────┐
│  nginx (proxy)                                      │
│    /api/      →  stac-fastapi (internal)            │
│    /external/ →  stac-fastapi (external)            │
│    /          →  stac-browser                       │
└─────────────────────────────────────────────────────┘
         │                         │
 stac-fastapi (internal)   stac-fastapi (external)
         │                         │
         └──────────┬──────────────┘
                    │
              PostgreSQL
              (pgSTAC schema)

NFS  ─────────────── mounted on server + workstations
```

Services: `db`, `api-internal`, `api-external`, `browser`, `proxy`

---

## Data Model

### STAC item types

The catalogue contains three types of STAC item, unchanged from the current design:

- **MatchupEvent** — one item per satellite crossover opportunity (one Collection per sensor pair)
- **Matchup** — one item per product pair found within an event (`derived_from` links back to the source ProductItems)

### Asset conventions

Assets are stored as entries in the STAC item `assets` dict. The key convention
determines which catalogue (internal or external) exposes them:

| Asset href scheme | Visible in internal API | Visible in external API |
|-------------------|------------------------|------------------------|
| `file:///...`     | Yes | No |
| `http://...`      | Yes | Yes |

All current assets (downloaded EO products, analysis NetCDFs) use `file://` hrefs
pointing to NFS paths and are internal-only. If NPL ever wants to expose processed
data to external users, it can be served over HTTP from the NFS and the href
updated accordingly — no schema changes required.

### Versioned analysis assets

After the processing pipeline produces a comparison NetCDF, it registers the result
as a versioned asset on the corresponding Matchup item. The asset key uses a
datestamp to preserve history:

```json
{
  "assets": {
    "comparison:latest":     {"href": "file:///npl-data/analysis/2022/05/21/matchup-123_comparison_20260510.nc", "type": "application/x-netcdf", "title": "Spectral comparison (latest)"},
    "comparison:2026-05-10": {"href": "file:///npl-data/analysis/2022/05/21/matchup-123_comparison_20260510.nc", "type": "application/x-netcdf", "title": "Spectral comparison"},
    "comparison:2026-01-15": {"href": "file:///npl-data/analysis/2022/05/21/matchup-123_comparison_20260115.nc", "type": "application/x-netcdf", "title": "Spectral comparison"}
  }
}
```

`latest` is always updated to point to the most recent version. Older versions are
retained so results can be reproduced against a specific analysis run.

---

## Access Control

### Read access

All GET requests on both the internal and external APIs are unauthenticated. Access
is controlled at the network level — the server sits behind the NPL VPN.

When the service is later deployed to cloud, a login requirement can be added at
the nginx layer without any application code changes.

### Write access

Write requests (POST, PUT, DELETE) on the internal API require an API key passed
as a Bearer token:

```
Authorization: Bearer <api-key>
```

nginx checks this header before forwarding to stac-fastapi. The external API has
no write endpoints exposed at all.

API keys are stored in the nginx config and distributed to users who need to write
to the central catalogue (pipeline service account, authorised researchers). Key
rotation is handled by updating the nginx config and reloading.

### Internal vs external catalogue

Both stac-fastapi instances point at the same PostgreSQL database. The difference
is a response filter in the external instance that strips any asset whose `href`
starts with `file://` before returning the item. This gives a clean separation
without duplicating data or introducing a sync step.

---

## Write Path

Files remain the source of truth. The pipeline:

1. Runs `eomatch-find` → writes local pystac files as now
2. Runs `eomatch-ingest` → pushes items to pgSTAC via pypgstac bulk loader

`eomatch-ingest` uses pypgstac directly (bypassing the HTTP API) for bulk
efficiency and connects to the database via the credentials in the `ingest` config
section or CLI flags (`--db-host`, `--db-user`, etc.).

Ingest is idempotent: pypgstac uses upserts, so re-running after a partial failure
or re-processing is safe.

---

## User Workflows

### 1. Central pipeline (automated or manual)

```
eomatch-find --config run.yaml
    → writes pystac files to local/shared catalogue

eomatch-ingest --config run.yaml
    → pushes new items to pgSTAC (upsert, safe to re-run)

eomatch-download --config run.yaml
    → downloads EO products from CEDA/AWS to NFS

[processing pipeline]
    → reads products from NFS
    → runs analysis
    → writes comparison NetCDF to /npl-data/analysis/...
    → calls register_analysis(catalogue_path, collection_id, item_id, file_path)
    → eomatch updates the STAC item with new versioned asset
```

### 2. Internal researcher

```
eomatch-query --api-url http://server/api/ \
    --start-time "2022-01-01" --end-time "2022-12-31" \
    --output ./my_catalogue
    → pulls matching items from pgSTAC to local pystac files

[Python]
from eomatch import MatchupCatalogue
cat = MatchupCatalogue.open("./my_catalogue/catalog.json")
for event in cat.get_events():
    for matchup in event.matchup_set:
        ds = matchup.return_matchup_dataset()   # reads from NFS, no download
        # analyse...
```

### 3. External user

```
eomatch-query --api-url http://server/external/ \
    --start-time "2022-01-01" --end-time "2022-12-31" \
    --output ./my_catalogue

eomatch-download --path ./my_catalogue
    → downloads EO products from CEDA/AWS (user's own credentials)

[Python]
cat = MatchupCatalogue.open("./my_catalogue/catalog.json")
for event in cat.get_events():
    for matchup in event.matchup_set:
        ds = matchup.return_matchup_dataset()
        # analyse...
```

---

## New CLI Commands

### `eomatch-ingest`

Push a local pystac catalogue into pgSTAC.

```
eomatch-ingest [--config CONFIG] [--catalogue PATH]
               [--db-host HOST] [--db-port PORT] [--db-name NAME] [--db-user USER]
               [--assets-base-url URL]
```

- `--catalogue`: path to local `catalog.json` (defaults to `matchup_catalogue.path` from config)
- `--db-host/port/name/user`: database connection parameters (fall back to `ingest.*` in config)
- `--assets-base-url`: rewrite relative asset hrefs to HTTP URLs served by the proxy

### `eomatch-query`

Pull items from a remote STAC API to a local pystac catalogue.

```
eomatch-query [--config CONFIG] --api-url URL --output PATH \
    [--start-time T] [--end-time T] [--bbox W S E N] \
    [--collections C1,C2]
```

Accepts the same spatial/temporal filters as `eomatch-find`. Writes a local
pystac catalogue that the existing toolchain (`eomatch-download`, `BuildMUDT`,
etc.) can work with directly.

### Analysis registration (Python API + CLI)

```python
# Python
from eomatch.add_asset import register_analysis

register_analysis(
    catalogue_path="/data/my_catalogue",
    collection_id="LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A",
    item_id="matchup-123",
    file_path="/npl-data/analysis/2022/05/21/matchup-123_comparison_20260510.nc",
)
```

```
# CLI
eomatch-add-asset \
    --catalogue /data/my_catalogue \
    --collection-id LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A \
    --item-id matchup-123 \
    --file /npl-data/analysis/matchup-123_comparison_20260510.nc
```

`register_analysis` generates a dated key (`comparison:YYYY-MM-DD`) and updates
`comparison:latest`, writing the result to the local pystac file.  Pass
``push=True`` (Python) or ``--push`` (CLI) to also upsert the item directly into
the running pgSTAC database.

---

## Implementation Phases

### Phase 1 — Core infrastructure

- Docker Compose stack: `postgres`, `api-internal`, `browser`, `proxy`
- `eomatch-ingest` command (pypgstac bulk loader)
- API-key auth on writes via nginx
- Verify end-to-end: find → ingest → browse in STAC Browser

### Phase 2 — External catalogue & query

- `api-external` service with asset filtering middleware
- STAC Browser configured for external endpoint
- `eomatch-query` command
- Verify external workflow: query → download → BuildMUDT

### Phase 3 — Analysis registration

- `register_analysis()` Python API (`eomatch.add_asset`)
- `eomatch-add-asset` CLI command
- Versioned asset key logic (`comparison:YYYY-MM-DD` + `comparison:latest`)
- Config keys: `ingest.db_host`, `ingest.db_name`, `ingest.db_user` (password via `PGPASSWORD`)

### Phase 4 — Hardening

- Logging and monitoring for the Docker Compose services
- Scheduled ingest job (cron or systemd timer) for the pipeline
- Documentation for external users

---

## Cloud Migration Path

The Docker Compose stack is deployment-agnostic. To move from on-prem to cloud:

1. Provision a VM (AWS EC2, Azure VM, or similar) and copy the Compose file
2. Mount an equivalent network share (EFS, Azure Files) at the same NFS path
3. Update `POSTGRES_HOST` and any volume paths in the Compose environment
4. Optionally: add HTTPS at the nginx layer via Let's Encrypt

File-based asset hrefs (`file:///npl-data/...`) remain valid as long as the NFS is
mounted at the same path on the new host. If paths change, a one-off migration
script can update asset hrefs in pgSTAC directly via SQL.
