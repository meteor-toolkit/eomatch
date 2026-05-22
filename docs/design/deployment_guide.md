# Setting Up the Central Catalogue (Phase 1)

This guide walks through standing up the eomatch central catalogue on an
on-prem server and ingesting your first local catalogue into it.

It assumes no prior experience with Docker or server administration.

---

## What you need

- A Linux server (Ubuntu 22.04 LTS recommended) accessible over the NPL network.
  A modest spec is fine to start: 4 CPU cores, 16 GB RAM, 100 GB disk.
- SSH access to the server.
- The eomatch repository on both the server and your local machine.

---

## Part 1 — Set up the server

### 1.1 Install Docker

SSH into the server and run:

```bash
# Download and run the official Docker install script
curl -fsSL https://get.docker.com | sh

# Add your user to the docker group so you don't need sudo every time
sudo usermod -aG docker $USER

# Log out and back in for the group change to take effect
exit
```

SSH back in and verify it worked:

```bash
docker compose version
# Should print something like: Docker Compose version v2.x.x
```

### 1.2 Get the deploy files onto the server

The easiest way is to clone the eomatch repository:

```bash
git clone git@gitlab.npl.co.uk:eco/tools/eomatch.git
cd eomatch/deploy
```

If you only want the deploy files (not the full repo), you can copy just the
`deploy/` directory from your local machine:

```bash
# Run this on your local machine
scp -r /path/to/eomatch/deploy user@your-server:/home/user/eomatch-deploy
```

### 1.3 Configure the environment file

The `.env` file holds passwords and other settings. Copy the template and edit it:

```bash
cp .env.example .env
nano .env          # or use vim, or any editor you prefer
```

The file looks like this — fill in the two passwords:

```
POSTGRES_DB=eomatch
POSTGRES_USER=postgres
POSTGRES_PASSWORD=         ← set a strong password here

INGEST_API_KEY=            ← set a random key here

LISTEN_PORT=8000
POSTGRES_LISTEN_PORT=5432
```

To generate secure random values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run it twice — once for `POSTGRES_PASSWORD`, once for `INGEST_API_KEY`. Write
these down somewhere safe (e.g. a password manager); you will need them later.

### 1.4 Configure the STAC Browser URL

The STAC Browser needs to know the address of the API. Copy the example config
and edit it:

```bash
cp browser/config.js.example browser/config.js
nano browser/config.js
```

Change `your-server:8000` to the actual hostname or IP address of the server:

```js
window.STAC_BROWSER_CONFIG = {
  catalogUrl: "http://192.168.1.100:8000/api/",   // ← your server's address
  catalogTitle: "EOMatch Catalogue",
  allowSelectCatalog: false,
};
```

### 1.5 Start the stack

```bash
docker compose up -d
```

The `-d` flag runs everything in the background. The first time you run this,
Docker has to:
- Download the PostgreSQL and stac-fastapi images (~500 MB total)
- Build the STAC Browser from source (this takes 5–10 minutes)

Subsequent starts skip all of this and are fast.

Watch the startup progress:

```bash
docker compose logs -f
```

Press `Ctrl+C` to stop watching logs (the services keep running).

### 1.6 Verify everything is running

```bash
docker compose ps
```

All five services should show `running`:

```
NAME                    STATUS
deploy-db-1             running
deploy-api-internal-1   running
deploy-api-external-1   running
deploy-browser-1        running
deploy-proxy-1          running
```

Test the API from the server itself:

```bash
curl http://localhost:8000/api/
```

You should get a JSON response starting with `{"type":"Catalog",...}`.

Open a browser on your local machine and go to:
```
http://your-server-address:8000/
```

You should see the STAC Browser UI. The catalogue will be empty at this point —
that's expected.

---

## Part 2 — Ingest a local catalogue

Now you can push a eomatch catalogue that you've built locally into the
central database.

### 2.1 Install eomatch with the ingest extra

On your local machine (or wherever you run `eomatch-find`):

```bash
pip install -e '.[ingest]'
```

This installs `pypgstac`, the library that loads items into the database.

### 2.2 Add the database connection to your config

Open your eomatch user config (`~/.config/eomatch/user_config.yaml`) and
fill in the `ingest` section:

```yaml
ingest:
  db_host: your-server-address   # ← the server's hostname or IP
  db_port: 5432
  db_name: eomatch
  db_user: postgres
  db_password:                   # ← leave blank, use env var below
```

Leaving `db_password` blank and passing it via an environment variable avoids
storing credentials in a config file.

### 2.3 Run the ingest

```bash
# Set the password as an environment variable (it won't appear in shell history)
export PGPASSWORD=your-postgres-password

# Run the ingest (reads catalogue path from your config, or pass --catalogue)
eomatch-ingest --config my_run.yaml

# Or pass everything explicitly
eomatch-ingest \
    --catalogue /path/to/my/catalogue \
    --db-host your-server-address \
    --db-user postgres
```

You'll see progress like:

```
2026-05-10 14:23:01 INFO eomatch.ingest: Opening catalogue: /path/to/catalogue/catalog.json
2026-05-10 14:23:02 INFO eomatch.ingest: Connecting to pgSTAC at your-server:5432/eomatch
2026-05-10 14:23:02 INFO eomatch.ingest: Loading 3 collection(s)
2026-05-10 14:23:03 INFO eomatch.ingest: Loading 47 item(s)
2026-05-10 14:23:04 INFO eomatch.ingest: Ingest complete — 3 collection(s), 47 item(s)
```

Ingest is **idempotent** — you can run it again after adding more matchups and
it will add only the new items without duplicating existing ones.

### 2.4 Check the STAC Browser

Refresh the STAC Browser at `http://your-server:8000/`. Your collections and
matchup items should now appear.

---

## Part 3 — External API and querying

The stack exposes a second read-only endpoint at `/external/` that strips
`file://` asset hrefs before responding.  This is safe to share with
collaborators outside NPL — they see collections and item metadata, but not
internal NFS paths.

### 3.1 Verify the external endpoint

From the server:

```bash
curl http://localhost:8000/external/
```

You should get the same `{"type":"Catalog",...}` response as from `/api/`,
but any items with `file://` assets will have those entries removed.

### 3.2 Query the external API from your local machine

Install the query extra on your local machine:

```bash
pip install -e '.[query]'
```

Pull a collection of matchup items to a local catalogue:

```bash
eomatch-query \
    --api-url http://your-server:8000/external/ \
    --output ./my_matchups \
    --collections LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A \
    --start-time 2022-01-01 \
    --end-time 2022-12-31
```

You will see progress like:

```
2026-05-10 15:19:16 INFO eomatch.query: Connecting to STAC API: http://your-server:8000/external/
2026-05-10 15:19:16 INFO eomatch.query: Searching with filters: {'collections': ['LANDSAT_C2L1-Landsat-9-vs-S2_MSI_L1C-S2A'], ...}
2026-05-10 15:19:17 INFO eomatch.query: Fetched 47 item(s) (47 new, 0 updated)
2026-05-10 15:19:17 INFO eomatch.query: Catalogue saved to ./my_matchups
```

The result is a local pystac catalogue in the same format that
`eomatch-find` produces.  Open it with `MatchupCatalogue`:

```python
from eomatch.mu_stac import MatchupCatalogue

cat = MatchupCatalogue.open("./my_matchups/catalog.json")
events = cat.get_events()
```

Run `eomatch-query` again at any time to pick up new items — existing
items are replaced with the latest version from the server (upsert).

### 3.3 Share the external URL with collaborators

The external endpoint at `http://your-server:8000/external/` is read-only
and contains no internal file paths, so it can be shared freely with anyone
who has network access to the server.

If you want to give external users a browser UI, point a second STAC Browser
instance at `/external/`:

```js
// browser/config-external.js
window.STAC_BROWSER_CONFIG = {
  catalogUrl: "http://your-server:8000/external/",
  catalogTitle: "EOMatch Catalogue (External)",
  allowSelectCatalog: false,
};
```

---

## Common problems

**`docker compose up` says "port is already in use"**

Something else is using port 8000 or 5432. Change `LISTEN_PORT` or
`POSTGRES_LISTEN_PORT` in `.env` to a different port number.

**The API returns a 500 error**

The database may still be starting up. Wait 30 seconds and try again. Check
the logs with `docker compose logs db` to see if PostgreSQL started cleanly.

**`eomatch-ingest` says "connection refused"**

Check that the server's firewall allows inbound connections on port 5432 from
your machine. On Ubuntu with `ufw`:

```bash
# On the server — allow postgres from a specific IP (replace with your machine's IP)
sudo ufw allow from 192.168.1.50 to any port 5432
```

Or allow from the whole NPL subnet:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 5432
```

**STAC Browser shows "Failed to fetch"**

The `catalogUrl` in `browser/config.js` is probably wrong. Double-check the
server address and port, then restart the browser container:

```bash
docker compose restart browser
```

---

## Keeping the service running

The Compose stack uses `restart: unless-stopped`, so services automatically
restart after a server reboot. No extra configuration needed.

To stop everything cleanly:

```bash
docker compose down          # stops containers, keeps database data
docker compose down -v       # stops containers AND deletes database (destructive!)
```

---

## Scheduled ingest

Running `eomatch-ingest` on a regular schedule keeps the central catalogue
up to date as new matchups are discovered.  The ingest command is idempotent,
so running it more often than necessary is harmless.

The recommended approach is a **systemd timer** on the machine where eomatch
is installed (typically the pipeline server or your workstation).  A crontab
entry is a simpler alternative if you prefer it.

### Option A — systemd timer (recommended)

Create two files on the machine that runs `eomatch-ingest`.

**`/etc/systemd/system/eomatch-ingest.service`**

```ini
[Unit]
Description=Push eomatch catalogue to pgSTAC
After=network-online.target

[Service]
Type=oneshot
User=<your-username>
ExecStart=eomatch-ingest --config /path/to/my_run.yaml
StandardOutput=journal
StandardError=journal
```

**`/etc/systemd/system/eomatch-ingest.timer`**

```ini
[Unit]
Description=Run eomatch-ingest daily at 02:00

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start the timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now eomatch-ingest.timer

# Verify it is scheduled
systemctl list-timers eomatch-ingest.timer
```

`Persistent=true` means if the machine was off at 02:00, the ingest runs as
soon as it comes back online.

Check logs with:

```bash
journalctl -u eomatch-ingest.service -n 50
```

### Option B — crontab

On the machine running eomatch, open the crontab editor:

```bash
crontab -e
```

Add a line to run ingest daily at 02:00, logging output to a file:

```cron
0 2 * * * eomatch-ingest --config /path/to/my_run.yaml >> /var/log/eomatch-ingest.log 2>&1
```

Rotate the log file to avoid it growing unboundedly — add
`/etc/logrotate.d/eomatch-ingest`:

```
/var/log/eomatch-ingest.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
}
```

---

## Log management

Docker's default logging driver writes container logs to JSON files on the
host with no size limit, which can fill the disk on a busy server.  The
`docker-compose.yml` in this repository configures a 10 MB rolling log with
five rotated files per service (50 MB cap per service, 250 MB total across
the stack).

To inspect logs:

```bash
docker compose logs -f proxy          # follow nginx access and error logs
docker compose logs -f api-internal   # follow stac-fastapi logs
docker compose logs --since 1h db     # last hour of postgres logs
```

To check how much disk the logs currently occupy:

```bash
docker system df -v | grep -E "CONTAINER|LOG SIZE"
```

If you need to preserve logs beyond the five-file window, redirect container
stdout to a log aggregator (e.g. Loki, ELK) by changing the `logging.driver`
in `docker-compose.yml` from `json-file` to your aggregator's driver.  The
Loki driver is a common lightweight choice for on-prem:

```yaml
x-logging: &default-logging
  driver: loki
  options:
    loki-url: "http://localhost:3100/loki/api/v1/push"
    max-size: "10m"
    max-file: "5"
```
