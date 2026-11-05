# PLANO — gdrv-sync: Docker + UI HTML para sync de pasta local ↔ nuvem

Status: atualizado 2026-11-04 (abas por provedor + pasta local por provedor + healthcheck v1)
Escopo v1: **3 tarefas independentes, uma por provedor** (Google Drive, Dropbox, OneDrive Personal). Cada provedor tem **aba própria na UI** com suas configs e **pasta local fixa** dentro do volume montado: `/sync/Gdrive`, `/sync/Dropbox`, `/sync/Onedrive` (criadas automaticamente). Somente pastas na nuvem; **a raiz do provedor é selecionável**; intervalo fixo por tarefa; direção por tarefa.
Providers v1: **Google Drive (`gdrive`), Dropbox (`dropbox`), OneDrive Personal (`onedrive`)**. Box ficou fora (exige app próprio); SharePoint/OneDrive Business = fase futura.

## 1. Arquitetura (1 container)

```
┌─────────────────────────── container: gdrv-sync ───────────────────────────┐
│  FastAPI (uvicorn :8080)                                                 │
│   ├─ UI HTML (Jinja2): Settings com ABAS por provedor / Status / Connect │
│   ├─ /api/settings  → grava /data/settings.json (3 tarefas)              │
│   ├─ /browse        → rclone lsd <remote>:... (picker, aba ativa)        │
│   ├─ /connect       → rclone authorize <provider> → OAuth no browser     │
│   ├─ /healthz       → liveness + estado agregado por provedor            │
│   └─ sync_loop      → scheduler: fila com lock global, next_due por prov.│
│  /data (volume) ← rclone.conf, settings.json, bisync-state, logs/       │
│  /sync  (bind)  ← pasta local definida no docker-compose                 │
│     └─ /sync/Gdrive · /sync/Dropbox · /sync/Onedrive  (auto-criadas)     │
└───────────────────────────────────────────────────────────────────────────┘
```

## 2. Stack de arquivos

```
GD-SYNC-FOLDER/
├── docker-compose.yml      # portas 8080 + 53682, volumes ./data e LOCAL_SYNC_DIR:/sync, healthcheck
├── Dockerfile              # python:3.12-slim + rclone (estático) + uvicorn
├── app/
│   ├── main.py             # FastAPI + rotas HTML/API + /healthz
│   ├── sync_loop.py        # thread do ciclo; lê settings.json por mtime
│   ├── rclone_ops.py       # wrappers subprocess: sync/bisync/lsd/authorize
│   ├── providers.py        # metadados p/ provider (nome, remoto, raiz, exige client_id?)
│   └── templates/
│       ├── base.html       # nav + badges (conectado? container healthy?)
│       ├── settings.html   # form provider/direção/intervalo/remote + botão Conectar
│       ├── browse.html     # picker de pastas (drill-down + breadcrumb)
│       └── status.html     # últimas execuções, exit code, cauda do log
├── docs/
│   ├── PLANO.md            # este arquivo
│   └── OPENSOURCES.md      # pesquisa de reuso
├── mockup/index.html       # mockup estático aprovado
├── data/                   # volume (gitignored)
└── .gitignore              # data/, __pycache__, *.log
```

## 3. Configuração (`/data/settings.json`)

```json
{
  "providers": {
    "gdrive":   {"enabled": false, "direction": "bisync", "interval_min": 5, "remote": "gdrive:GD-SYNC", "local_sub": "Gdrive"},
    "dropbox":  {"enabled": false, "direction": "upload", "interval_min": 5, "remote": "dropbox:", "local_sub": "Dropbox"},
    "onedrive": {"enabled": false, "direction": "download", "interval_min": 10, "remote": "onedrive:", "local_sub": "Onedrive"}
  },
  "extra_flags": []
}
```

- **1 tarefa por provedor (v1)**: configs independentes (direção, intervalo, remoto, enable). `remote` vazio (`gdrive:` / `onedrive:` / `dropbox:`) → **raiz do provedor** (permitido).
- **`local_sub` é fixo por convenção** (`Gdrive`|`Dropbox`|`Onedrive`) — a app cria `/sync/<local_sub>` automaticamente no startup; NÃO é selecionável na UI.
- **Pasta local raiz vem do docker-compose** (`${LOCAL_SYNC_DIR:-./local}` → `/sync`); a UI exibe o indicativo read-only `~/SyncDrive → /sync`.
- `remote` da tarefa deve pertencer ao remote homônimo autenticado no `rclone.conf`.
- UI revalida na API: tarefa sem remote autenticado → bloqueia `enabled` dela (as outras seguem funcionando).

## 4. Comandos de sync executados (`L` = `/sync/<local_sub>` da aba, `R` = remote p.ex. `gdrive:GD-SYNC`)

| Direção | Comando |
|---|---|
| upload | `rclone sync $L $R` |
| download | `rclone sync $R $L` |
| bisync | 1ª execução: `rclone bisync $L $R --resync`; depois: `rclone bisync $L $R` |

- Flags base: `--config /data/rclone.conf`, `--log-file /data/logs/sync-<provider>-<ts>.log`, `--timeout 55m`, `--retries 3`.
- Bisync mantém `--check-access` (padrão) e estado em `/data/rclone-state/<provider>/` (não mover sem `--resync`).
- `sync` (one-way) **deleta extras no destino** — deixar isso explícito na UI.

## 5. Autenticação (Opção A — OAuth "dentro do HTML", genérica por provider)

Fluxo `POST /connect` (com `provider` no body) → página de progresso:
1. App dispara `rclone authorize <provider> --port 53682` (subprocess, stdout em modo linha).
2. Extrai a URL `https://accounts.<provider>.com/...` do stdout → **redireciona o browser do usuário**.
3. Usuário loga → callback cai em `localhost:53682` (porta publicada no compose; OAuth "desktop" aceita loopback em qualquer porta).
4. O rclone imprime o token blob no stdout → app captura e grava a seção `<provider>` no `/data/rclone.conf` (via `rclone config` não-interativo / stdin).
5. UI verifica com `rclone lsd <provider>:` → mostra ✅ Conectado ou erro.

Por provider:
- **gdrive / onedrive**: client_id embutido do rclone funciona out-of-the-box.
- **dropbox**: funciona out-of-the-box, mas o client embutido é compartilhado/rate-limited → a UI mostra campos **opcionalais "Avançado"** (`client_id`/`client_secret`) recomendados para uso pesado.
- Campos Avançado valem para qualquer provider (upgrade documentado); **Box** fica fora da v1 justamente por exigir client próprio.
- **UI da aba Conectar**: 3 blocos empilhados (um por provedor, ordem fixa Google Drive / Dropbox / OneDrive), cada um com status próprio, botão "Conectar" e lista de passos inline — sem dropdown de troca. Autorização de um provedor não afeta os demais.
- Sem copiar/colar pelo usuário. README documenta service-account (Drive) e client_id próprio como upgrades.

## 6. Picker de pastas do provedor (`/browse`)

- `rclone lsd <provider>:/CAMINHO --config /data/rclone.conf` → lista **somente pastas** (não lista arquivos).
- Breadcrumb clicável; botão "Selecionar esta pasta" → POST no form de settings.
- Entradas especiais: `🏠 (raiz do provedor)` → `remote = "<provider>:"`.
- gdrive: pastas de Shared Drive só em fase futura (v1: só My Drive).
- Cache da listagem 30 s em memória para não martelar a API.
- Botão desabilitado com aviso "Conecte a nuvem primeiro" se não há auth.

## 7. Sync loop (scheduler multi-provedor)

- Thread daemon no mesmo processo da UI: mantém `next_due` por provedor; a cada tick, enfileira tarefas `enabled` vencidas; executa **um comando por vez (lock global)** para não estourar rate limits nem sobrecarregar CPU.
- Checa por tarefa: remoto `<provider>` autenticado no conf + `/sync/<local_sub>` existente (cria se não) + `remote` válido; executa; grava resultado no ring buffer por provedor (últimas ~50 execuções) e em `/data/logs/sync-<provider>-<ts>.log`.
- Re-lê `settings.json` por mtime a cada tick (mudanças na UI valem no ciclo seguinte; "Run now" força via fila prioritária).
- Se a execução de um provedor passa do intervalo dele, pula o tick seguinte desse provedor.
- Botão **Run now** na UI (thread-safe via fila + `threading.Event`).
- Expõe estado por provedor em memória (`running`, `last_ok`, `consecutive_failures`) consumido pelo `/healthz` e pela página de Status.

## 8. Healthcheck (v1 — desde o scaffold)

- `GET /healthz` (FastAPI): liveness + estado agregado:
```json
{"ok": true, "rclone": "v1.7x",
 "providers": {
   "gdrive":  {"connected": true,  "enabled": true,  "running": false, "last_ok": true, "consecutive_failures": 0},
   "dropbox": {"connected": true,  "enabled": false, "running": false, "last_ok": null, "consecutive_failures": 0},
   "onedrive": {"connected": false, "enabled": false, "running": false, "last_ok": null, "consecutive_failures": 0}
 }}
```
- Retorna `503` quando: binário rclone ausente/inválido (checado no startup, cacheado) **ou** `consecutive_failures ≥ 3` em **qualquer** provedor com `enabled=true`.
- Compose declara healthcheck (sem curl na imagem slim — stdlib Python):

```yaml
healthcheck:
  test: ["CMD","python","-c","import urllib.request as u;u.urlopen('http://127.0.0.1:8080/healthz',timeout=4)"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 15s
```

- UI: badge do container (healthy/degraded) no header, poll de `/healthz` a cada 30 s na página de Status.

## 9. docker-compose.yml (esqueleto)

```yaml
services:
  gdrv-sync:
    build: .
    container_name: gdrv-sync
    restart: unless-stopped
    ports:
      - "8080:8080"    # UI
      - "127.0.0.1:53682:53682"  # callback OAuth (loopback)
    volumes:
      - ./data:/data
      - ${LOCAL_SYNC_DIR:-./local}:/sync
    # healthcheck da seção 8
```

## 10. Dockerfile (esqueleto)

- `python:3.12-slim`
- download do binário rclone estático do release oficial (checksum)
- `pip install fastapi uvicorn jinja2`
- `COPY app/ /app/` → `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]`

## 11. Segurança

- UI sem login: bind published `127.0.0.1` por padrão no compose (usuário publica como quiser); documentar.
- Rclone.conf com refresh-tokens: volume `./data` fora do git (.gitignore).
- client_id/secret opcionais gravados só no `rclone.conf` do volume; nunca em settings.json.
- Nenhum segredo em imagem; nenhuma chamada externa além do rclone.

## 12. Fases de execução

1. Scaffold: Dockerfile, compose (com `healthcheck`), `.gitignore`, `/healthz` funcional desde o 1º boot (estado com os 3 provedores desligados).
2. UI Settings com **abas por provedor** + API + `settings.json` (configs independentes por tarefa) + criação automática de `/sync/<local_sub>`.
3. Picker de pastas do provedor (`/browse` por aba) + indicativo read-only da pasta local.
4. Fluxo `/connect` (Opção A por provider) + gravação de `rclone.conf` (remotes coexistem).
5. Scheduler multi-provedor (fila com lock global) + logs por provedor + `/status` + exposição p/ `/healthz`.
6. README: uso, primeiro login por provedor, tabela de pré-requisitos, service-account/client_id próprios como upgrades, "Plano B" (GUI oficial rclone).
7. Smoke-test: `docker compose build && up`, sem credenciais reais → validar abas, `/healthz`, picker vazio, mensagens de erro por provedor.

## 13. Fora do escopo (v1)

- Box; SharePoint/OneDrive Business; **múltiplas tarefas do mesmo provedor** (1 por aba); watch em tempo real; filtros include/exclude; criptografia (rclone crypt); Shared Drives no picker; TLS/reverse-proxy; multiusuário na UI.
