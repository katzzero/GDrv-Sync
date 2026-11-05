# gdrv-sync

FastAPI web UI + rclone subprocess scheduler in one Docker container that syncs
local folders to cloud providers (Google Drive, Dropbox, OneDrive Personal).

## Usage

The pre-built image is published on GHCR (multiarch: `linux/amd64` + `linux/arm64`):

```bash
docker pull ghcr.io/katzzero/gdrv-sync:latest
```

`docker-compose.yml` in this repo builds locally (`build: .`). To run from the
published image instead:

```yaml
services:
  gdrv-sync:
    image: ghcr.io/katzzero/gdrv-sync:latest   # vs. build: .
    container_name: gdrv-sync
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
      - "127.0.0.1:53682:53682"
    volumes:
      - ./data:/data
      - ${LOCAL_SYNC_DIR:-./local}:/sync
```

Or build locally:

```bash
docker compose up -d
```

Open http://localhost:8080 in your browser.

The OAuth callback port `53682` is published on `127.0.0.1` only (loopback) by
default in docker-compose.

### Local run (without Docker)

```bash
export DATA_DIR=./data
export LOCAL_SYNC_DIR=./local
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

## Non-root container

The image runs as a non-root user (`uid 1000`, user `gdrv-sync`) and writes to
`/data`.  When bind-mounting `./data`, ensure the host directory allows writes
by uid 1000 (Colima/Docker Desktop typically pass the host uid through).  If
`/data` is not writable, the app fails fast on startup (see `ensure_dirs`).

## First Setup

1. **Connect each provider** via the Cloud Connect tab ("Conectar Nuvem"):
   - Google Drive (gdrive) - works out of the box (rclone embedded client_id)
   - Dropbox (dropbox) - works out of the box; the embedded client is
     rate-limited, so set your own client_id/client_secret under the Advanced
     box ("Avançado") for heavy use
   - OneDrive (onedrive) - works out of the box (rclone embedded client_id)

   The flow opens the provider login in your browser and the callback lands on
   `localhost:53682` (published in compose). No copy/paste of tokens is needed.

2. **Configure sync tasks** in the Settings tab ("Configurações") — one tab per provider:
   - Fixed local folder: `/sync/Gdrive`, `/sync/Dropbox`, `/sync/Onedrive`
     (created automatically inside the `LOCAL_SYNC_DIR` volume)
   - Pick the cloud folder (leave empty for the provider root)
   - Direction: upload, download or bisync
   - Interval (minimum 5 minutes)
   - Enable the task

   A task can only be enabled once its provider is authenticated.

3. **Run now** via the Status tab to test immediately.

## Volumes

| Host | Container | Contents |
|------|-----------|----------|
| `./data` | `/data` | rclone.conf, settings.json, logs, bisync-state |
| `${LOCAL_SYNC_DIR:-./local}` | `/sync` | local folders: `/sync/Gdrive`, `/sync/Dropbox`, `/sync/Onedrive` |

## Provider Prerequisites

| Provider | Out-of-box | Notes |
|----------|------------|-------|
| Google Drive | ✅ | Uses rclone's embedded client_id |
| Dropbox | ✅ | Embedded client is rate-limited; use your own client_id/secret for heavy use (Advanced box) |
| OneDrive | ✅ | Uses rclone's embedded client_id |

## Advanced Options

### Service Account (Google Drive)

For elevated access, create a service account and configure rclone:

```bash
rclone config create gdrive drive
# Set service_account_file in config
```

Documented as an upgrade; not wired into the v1 UI.

### Custom Client ID (Dropbox)

On the Connect page, open the Advanced box ("Avançado") to set your own client_id/client_secret.
These are written only to `/data/rclone.conf` (the volume), never to
`settings.json`.

### Plan B - rclone GUI

For a no-code alternative, run the official rclone GUI:

```bash
docker run -p 5522:5522 -p 5533:5533 rclone/rclone:latest gui --addr 0.0.0.0:5522 --api-addr 0.0.0.0:5533
```

## API Endpoints

- `GET /` - Settings page (tabs per provider)
- `GET /connect` - Connect page (3 stacked provider boxes)
- `GET /status` - Status page (per-provider history + run-now)
- `GET /browse?provider=&path=` - Provider folder picker (breadcrumb + root)
- `GET /healthz` - Health check (JSON; 503 when rclone missing or any enabled provider has 3+ consecutive failures)
- `GET /api/settings` - Current settings
- `POST /api/settings` - Save provider settings (rejects `enabled=true` when not authenticated)
- `POST /api/connect/start` - Start OAuth flow (returns `auth_url`)
- `GET /api/connect/status?provider=` - OAuth connection status
- `POST /api/connect/cancel` - Cancel an in-flight authorize
- `POST /api/run-now` - Enqueue a priority sync run

## Health Check

`/healthz` returns:

```json
{
  "ok": true,
  "rclone": "v1.75.2",
  "providers": {
    "gdrive":  {"connected": true,  "enabled": true,  "running": false, "last_ok": true,  "consecutive_failures": 0},
    "dropbox": {"connected": true,  "enabled": false, "running": false, "last_ok": null, "consecutive_failures": 0},
    "onedrive":{"connected": false, "enabled": false, "running": false, "last_ok": null, "consecutive_failures": 0}
  }
}
```

Returns `503` when the rclone binary is missing/invalid **or** any provider with
`enabled=true` has `consecutive_failures >= 3`.

## Important notes

- **OAuth flow was NOT end-to-end tested with real accounts.** The authorize
  subprocess and URL/token capture are implemented, but completing a real
  OAuth dance requires actual provider credentials and a browser. Treat the
  connect flow as "implemented, to be validated with a real account."
- No auth on the UI; the container is intended for localhost/private use.
- Box, OneDrive Business/SharePoint, watch, filters, and multi-task-per-provider
  are out of scope (v1).

## License

This project is licensed under the **AGPL-3.0-only** (GNU Affero General Public License v3.0).
See the [LICENSE](LICENSE) file for details.

**rclone** is a separate program, licensed under the **MIT License**, downloaded
at Docker image build time.
