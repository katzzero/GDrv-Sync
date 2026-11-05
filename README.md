# gdrv-sync

FastAPI web UI + rclone subprocess scheduler in one Docker container that syncs
local folders to cloud providers (Google Drive, Dropbox, OneDrive Personal).

## Usage

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

1. **Connect each provider** via the "Conectar Nuvem" tab:
   - Google Drive (gdrive) - works out of the box (rclone embedded client_id)
   - Dropbox (dropbox) - works out of the box; the embedded client is
     rate-limited, so set your own client_id/client_secret under "Avançado" for
     heavy use
   - OneDrive (onedrive) - works out of the box (rclone embedded client_id)

   The flow opens the provider login in your browser and the callback lands on
   `localhost:53682` (published in compose). No copy/paste of tokens is needed.

2. **Configure sync tasks** in the "Configurações" tab (one tab per provider):
   - Pasta local fixa: `/sync/Gdrive`, `/sync/Dropbox`, `/sync/Onedrive`
     (criada automaticamente dentro do volume `LOCAL_SYNC_DIR`)
   - Escolha a pasta na nuvem (deixe vazio para a raiz do provedor)
   - Direção: upload, download ou bisync
   - Intervalo (mínimo 5 minutos)
   - Habilite a tarefa

   Uma tarefa só pode ser habilitada depois que o provedor estiver autenticado.

3. **Run now** via the "Status" tab para testar imediatamente.

## Volumes

| Host | Container | Conteúdo |
|------|-----------|----------|
| `./data` | `/data` | rclone.conf, settings.json, logs, bisync-state |
| `${LOCAL_SYNC_DIR:-./local}` | `/sync` | pastas locais: `/sync/Gdrive`, `/sync/Dropbox`, `/sync/Onedrive` |

## Provider Prerequisites

| Provider | Out-of-box | Notes |
|----------|------------|-------|
| Google Drive | ✅ | Usa client_id embarcado do rclone |
| Dropbox | ✅ | Client embarcado é rate-limited; use client_id/secret próprios em uso pesado (campo "Avançado") |
| OneDrive | ✅ | Usa client_id embarcado do rdrive |

## Advanced Options

### Service Account (Google Drive)

For elevated access, create a service account and configure rclone:

```bash
rclone config create gdrive drive
# Set service_account_file in config
```

Documented as an upgrade; not wired into the v1 UI.

### Custom Client ID (Dropbox)

In the Connect page, click "Avançado" to set your own client_id/client_secret.
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

## Licença / License

Este projeto está licenciado sob a **AGPL-3.0-only** (GNU Affero General Public License v3.0).
Veja o arquivo [LICENSE](LICENSE) para detalhes.

O **rclone** é um programa separado, licenciado sob a **MIT License**, e é baixado
durante o build da imagem Docker.
