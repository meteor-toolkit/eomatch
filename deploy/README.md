# EOMatch Central Catalogue — Deployment

Docker Compose stack for the eomatch central catalogue service.

## Services

| Service | Role |
|---------|------|
| `db` | PostgreSQL with pgSTAC schema |
| `api-internal` | stac-fastapi (full assets, write-enabled with API key) |
| `browser` | STAC Browser UI |
| `proxy` | nginx (routes `/api/` → API, `/` → Browser; enforces write auth) |

## Prerequisites

- Docker with Compose plugin (`docker compose version`)
- Internet access for the initial image pull and STAC Browser build
- NFS or equivalent network drive mounted on the host (for product and analysis assets)

## First-time setup

**1. Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` and set:
- `POSTGRES_PASSWORD` — a strong random password for the database
- `INGEST_API_KEY` — the key that `eomatch-ingest` will present on writes

Generate a secure key with:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**2. Configure the STAC Browser catalog URL**

```bash
cp browser/config.js.example browser/config.js
```

Edit `browser/config.js` and set `catalogUrl` to the address of the server:
```js
catalogUrl: "http://your-server-address:8000/api/",
```

**3. Start the stack**

```bash
docker compose up -d
```

The first run builds the STAC Browser from source — this takes several minutes.
Subsequent starts use the Docker layer cache and are fast.

**4. Verify**

- STAC Browser: http://your-server:8000/
- STAC API root: http://your-server:8000/api/

The API root should return a JSON landing page. The browser should load and
display the (initially empty) catalogue.

## Customising the STAC Browser

### Runtime settings (no rebuild needed)

`browser/config.js` is volume-mounted into the container, so any change takes
effect on the next page load.  See `browser/config.js.example` for the full
list of options — things like `catalogTitle`, default view mode, items per
page, and authentication settings can all be changed here.

### Branding — logo, colours, footer (rebuild required)

Visual customisation goes in two SCSS files that STAC Browser explicitly
reserves for user overrides and never changes upstream:

| File | Purpose |
|------|---------|
| `browser/theme/variables.scss` | Colour palette, font sizes, logo height |
| `browser/theme/custom.scss` | Arbitrary CSS/SCSS rules |

Copy the example files and edit them, then rebuild the browser container:

```bash
cp browser/theme/variables.scss.example browser/theme/variables.scss
cp browser/theme/custom.scss.example    browser/theme/custom.scss
# edit the files, then:
docker compose build browser
docker compose up -d browser
```

**Adding a logo**

Place a `logo.png` file in `browser/` alongside the Dockerfile.  It will be
served at `/logo.png`.  Then in `browser/theme/variables.scss` uncomment and
set the three logo variables:

```scss
$logo: 'image';             // switch the navbar from text to image mode
$logo-image: '/logo.png';   // path served by nginx
$logo-image-height: 2.5rem; // adjust to taste
```

**Explanatory text and API usage notes**

The catalogue `description` field (set in your eomatch config under
`matchup_catalogue.description`) is rendered as markdown by STAC Browser on
the landing page — this is the best place for "how to use this catalogue" and
CQL2 query examples.  A short footer notice can also be added via the
`custom.scss` footer block (see the commented-out example at the bottom of
`custom.scss.example`).

## Ingesting a local catalogue

Install `eomatch` with the ingest extra:

```bash
pip install 'eomatch[ingest]'
```

Configure connection details in your eomatch config (or pass on the CLI):

```yaml
# ~/.config/eomatch/user_config.yaml
ingest:
  db_host: your-server
  db_port: 5432
  db_name: eomatch
  db_user: eomatch
  db_password:   # leave blank, use PGPASSWORD env var
```

Run ingest:

```bash
export PGPASSWORD=your-db-password
eomatch-ingest --config my_run.yaml
```

Or with all parameters explicit:

```bash
eomatch-ingest \
    --catalogue /path/to/local/catalogue \
    --db-host your-server \
    --db-name eomatch \
    --db-user eomatch
```

Write operations to the STAC API (if using `--via-api` mode in future) require:

```
Authorization: Bearer <INGEST_API_KEY>
```

## Stopping and data persistence

```bash
docker compose down          # stop services, keep database volume
docker compose down -v       # stop services AND delete database (destructive)
```

The database lives in the `pgdata` Docker volume. Items are preserved across
restarts as long as this volume is not deleted.

## Upgrading

To upgrade pgSTAC or stac-fastapi versions, update the image tags in
`docker-compose.yml` and run:

```bash
docker compose pull
docker compose up -d
```

Check the pgSTAC and stac-fastapi-pgstac changelogs before upgrading across
major versions.

## Cloud migration

The Compose stack is deployment-agnostic. To move to a cloud VM:

1. Copy `docker-compose.yml`, `.env`, `nginx/`, `browser/` to the VM
2. Mount the NFS equivalent (EFS, Azure Files, etc.) at the same path
3. Update `catalogUrl` in `browser/config.js` to the new host address
4. Run `docker compose up -d`

To add HTTPS, put a TLS-terminating load balancer or Certbot/nginx in front
of the proxy service and update the port mapping in `docker-compose.yml`.
