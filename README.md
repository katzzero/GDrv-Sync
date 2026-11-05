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
      - "127.0.0.1:53682:53683"
    volumes:
      - ./data:/data
      - ${LOCAL_SYNC_DIR:-./local}:/sync
```

Or build locally:

```bash
docker compose up -d
```

Open http://localhost:8080 in your browser.

An internal TCP proxy (`app/callback_proxy.py`) forwards the published host port `53682` to the
rclone authorize loopback listener (`127.0.0.1:53682` in the container), because Docker
published ports cannot reach loopback-only listeners inside the container.

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
   - **Local folder** (inside `/sync`): defaults to one per provider — `Gdrive`, `Dropbox`, `Onedrive` (**independent** tasks; each cloud only ever sees its own local folder). **Hub mode:** type the *same* name in several tabs and that one local folder is copied to all those clouds. Tasks that are enabled lock this field.
   - **Dedicated cloud folder:** when the cloud destination is still the provider root and the task is disabled, a "📦 Criar/usar pasta dedicada GDrv-Folder" button creates (idempotent `rclone mkdir`) and adopts a dedicated sandbox folder as the destination. If the folder already existed with content, the app warns you to review before enabling Bidirectional/Mirror.
   - Pick another cloud folder via 📁 Navegar if you prefer.
   - Direction: upload, download or bisync (bisync propagates deletions both ways — the card says so).
   - Interval (minimum 5 minutes).
   - Enable the task.

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

## Bring your own client_id (Google Drive 2026 retirement)

Google is retiring rclone's shared Drive client_id in 2026. To keep connecting
Google Drive with your own OAuth app credentials:

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create/select a project.
2. **Enable the Google Drive API** for that project (APIs & Services → Library → Google Drive API).
3. **OAuth consent screen**: set User Type to **External**, add your email as a test user, finish the required fields.
4. **Credentials → Create credentials → OAuth client ID** → application type **Desktop app**.
5. Under **Authorized redirect URIs**, add BOTH:
   - `http://localhost:53682/`
   - `http://127.0.0.1:53682/`
6. Copy the **Client ID** and **Client Secret**.
7. On the gdrv-sync Connect page, open the Google Drive "Avançado" box, paste client_id/secret, and click **🔗 Conectar** (Reconnect if already connected).
8. The credentials are written only to `./data/rclone.conf` (the volume) — keep that volume private; it is already gitignored.

Reference: https://rclone.org/drive/#making-your-own-client-id

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
- `POST /api/settings` - Save provider settings (rejects `enabled=true` when not authenticated; `mirror=true` requires `confirm_mirror=true` and is rejected for `direction=bisync`; `local_sub` validated to safe names — same name across providers = hub mode)
- `POST /api/use-dedicated` - Create & adopt the sandbox folder `<provider>:GDrv-Folder` (only when remote is root/empty and task disabled; warns if the folder already had content)
- `POST /api/preview` - Dry-run preview of the exact effective command (+ `--dry-run`), read-only, never mutates
- `POST /api/connect/start` - Start OAuth flow (returns `auth_url`)
- `GET /api/connect/status?provider=` - OAuth connection status
- `POST /api/connect/cancel` - Cancel an in-flight authorize
- `POST /api/connect/complete` - Server-side completion: persist captured token to rclone.conf
- `POST /api/run-now` - Enqueue a priority sync run

## Safety / Non-destructive by default

**Nothing is ever deleted by default, in either direction.**

- **Default (no mirror):** both upload and download run `rclone copy` (never `rclone sync`). `copy` never removes anything from the destination, so neither the cloud nor the local folder can lose files.
  - upload: `rclone copy /sync/<sub> <remote>`
  - download: `rclone copy <remote> /sync/<sub>`
- **Bisync:** `rclone bisync ... --conflict-resolve none` — on conflict the run aborts, no side wins. First-run `--resync` and `--check-access` defaults are unchanged.
- **Mirror mode (opt-in per provider, `mirror: false` default):** only when you explicitly opt in does the app run `rclone sync` + `--backup-dir`, so destination-only files are *moved* to a backup folder instead of hard-deleted:
  - upload → cloud backup-dir `<provider>:.gdrv-deleted/<UTC-YYYYMMDD-HHMMSS>` at the **provider root** (a sibling of the destination, never inside it — rclone rejects an overlapping backup-dir). Mirror + upload **to the drive root is blocked (HTTP 400)** because there would be nowhere to keep the backup.
  - download → local backup-dir `/data/deleted/<provider>/<UTC-ts>` (visible in the host `./data` volume).
  - Mirror is **not allowed for bisync** (the UI hides it; the API rejects it with 400) because bisync is already bidirectional and mirror would double the risk.
- **Confirmation guard:** saving `mirror=true` via `POST /api/settings` requires body field `confirm_mirror=true`; otherwise the API returns `400 {"ok":false,"error":"confirm_required",...}`. An extra warning appears when the remote is the provider root (`<provider>:`) with mirror+upload, since the whole cloud drive becomes the destination.
- **Dry-run preview:** every provider tab has a "🔍 Prévia (dry-run)" button that calls `POST /api/preview`, builds the exact effective command (mirror/backup-dir/bisync first-run included) plus `--dry-run`, runs it via rclone with a 120s timeout, and returns transfer/deletion counts plus the command lines. Nothing is ever mutated; a log is written to `/data/logs/preview-<provider>-<ts>.log`. Rows showing `Deleted:` are highlighted in red with a note pointing to the mirror/backup behavior.
- The scheduler computes a fresh backup-dir timestamp per run and records the mode (`copy` vs `sync+backup` vs `bisync`) in each `RunRecord`/log line.

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
