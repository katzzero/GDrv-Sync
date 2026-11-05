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
    "gdrive":   {"enabled": false, "direction": "upload", "interval_min": 5, "remote": "gdrive:GDrv-Folder", "local_sub": "Gdrive", "mirror": false},
    "dropbox":  {"enabled": false, "direction": "upload", "interval_min": 5, "remote": "dropbox:", "local_sub": "Dropbox", "mirror": false},
    "onedrive": {"enabled": false, "direction": "download", "interval_min": 10, "remote": "onedrive:", "local_sub": "Onedrive", "mirror": false}
  },
  "extra_flags": []
}
```

- **1 tarefa por provedor (v1)**: configs independentes (direção, intervalo, remoto, enable). `remote` vazio (`gdrive:` / `onedrive:` / `dropbox:`) → **raiz do provedor** (permitido).
- **`mirror`**: novo booleano por provedor, padrão `false` (não destrutivo). Quando `true`, `rclone sync` leva `--backup-dir` e arquivos extras no destino são *movidos* para o backup-dir em vez de apagados. Não permitido para bisync (API rejeita com 400).
- **`confirm_mirror`**: campo apenas no corpo de `POST /api/settings`. Obrigatório quando `mirror=true`; senão → 400 `{"ok":false,"error":"confirm_required",...}`. Não é persistido (serve só de confirmação da ação).
- **`local_sub` é configurável por provedor** (default `Gdrive`|`Dropbox`|`Onedrive`, um por aba = **independentes**; a app cria `/sync/<local_sub>` automaticamente). **Modo hub:** usar o MESMO nome em várias abas faz a mesma pasta local ser copiada para todas aquelas nuvens. Validação: `[A-Za-z0-9][A-Za-z0-9 _-]{0,63}` (sem `/`, sem `..`); tarefa habilitada ⇒ campo travado na UI.
- **§6a. Pasta dedicada (`GDrv-Folder`)**: na aba Settings, quando o remote está em raiz/vazio e a tarefa desabilitada, aparece o botão "📦 Criar/usar pasta dedicada" → `POST /api/use-dedicated`: roda `rclone mkdir <prov>:GDrv-Folder` (idempotente), checa se a pasta **já tinha conteúdo** (`lsjson` files+dirs) e grava `remote = <prov>:GDrv-Folder`. Se já existia com dados ⇒ aviso de adoção ("revise antes de bisync/espelho"). Nunca age sobre tarefa habilitada nem sobre remote já configurado (400); falha de mkdir não quebra o connect (endpoint separado, best-effort).
- **Pasta local raiz vem do docker-compose** (`${LOCAL_SYNC_DIR:-./local}` → `/sync`); a UI exibe o indicativo read-only `~/SyncDrive → /sync`.
- `remote` da tarefa deve pertencer ao remote homônimo autenticado no `rclone.conf`.
- UI revalida na API: tarefa sem remote autenticado → bloqueia `enabled` dela (as outras seguem funcionando).

## 4. Comandos de sync executados (`L` = `/sync/<local_sub>` da aba, `R` = remote p.ex. `gdrive:GD-SYNC`)

### 4.1 Padrão (não destrutivo — nunca apaga nenhum lado)

| Direção | Comando |
|---|---|
| upload | `rclone copy $L $R` |
| download | `rclone copy $R $L` |
| bisync | 1ª execução: `rclone bisync $L $R --conflict-resolve none --resync`; depois: `rclone bisync $L $R --conflict-resolve none` |

Flags base: `--config /data/rclone.conf`, `--log-file /data/logs/sync-<provider>-<ts>.log`, `--timeout 55m`, `--retries 3`.

**Nunca deleta**: `copy` não remove nada do destino. Bisync usa `--conflict-resolve none` (conflito = aborta, nenhum lado vence) + `--check-access` padrão + primeiro-run `--resync` inalterado.

### 4.2 Modo espelho (opt-in, `mirror=true`, apenas upload/download)

| Direção | Comando |
|---|---|
| upload (mirror) | `rclone sync $L $R --backup-dir "<provider>:.gdrv-deleted/<UTC-YYYYmmdd-HHMMSS>"` |
| download (mirror) | `rclone sync $R $L --backup-dir "/data/deleted/<provider>/<UTC-YYYYmmdd-HHMMSS>"` |
| bisync (mirror) | **não permitido** (UI oculta; API rejeita 400) |

- `--backup-dir` fica no **lado destino**, mas NUNCA pode sobrepor o destino (o rclone rejeita com "mustn't overlap"): para upload, a pasta `.gdrv-deleted/<ts>` fica na **raiz do provedor** (irmã do destino, não dentro dele — por isso **mirror + upload para a raiz é bloqueado com 400**, pois não haveria onde colocar o backup); para download, `./data/deleted/<provider>/<ts>` (visível ao usuário no volume host). Arquivos que existem no destino mas não na origem são *movidos* para lá (não apagados de verdade).
- ts é recalculado a cada execução pelo scheduler.
- API: `POST /api/settings` com `mirror=true` exige `confirm_mirror=true`, senão 400. Aviso extra forte quando `remote == "<provider>:"` (raiz) + mirror+upload (todo o Drive vira destino).

## 4.3 Prévia dry-run (somente leitura)

`POST /api/preview {provider, direction, remote, mirror}` → constrói o comando exato efetivo (incl. mirror/backup-dir/primeiro-run bisync) + `--dry-run`, executa via rclone_ops com timeout 120s, nunca muta nada. Retorna `{ok, rc, transfers, deletions, lines (tail até 80 sanitizadas), cmd}` e grava log em `/data/logs/preview-<provider>-<ts>.log`. UI mostra botão "🔍 Prévia (dry-run)" por aba com painel "N copias · M deleções" + linhas do comando; deleções>0 destacadas em vermelho com nota apontando ao comportamento do mirror/backup-dir.

### 4.4 Antigo comportamento `rclone sync` (removido)

O `rclone sync` puro (que deleta extras no destino) **não é mais o padrão**. Ele só aparece agora atrás do opt-in "Modo espelho" (+ `--backup-dir`), para que nada seja apagado sem consentimento explícito.

## 5. Autenticação (Opção A — OAuth "dentro do HTML", genérica por provider)

Fluxo `POST /connect` (com `provider` no body) → página de progresso:
1. App dispara `rclone authorize <backend>` (backend = `drive`/`dropbox`/`onedrive` via `providers.rclone_type`; **não existe flag `--port`** — o rclone escuta sempre em `127.0.0.1:53682` dentro do container, com `--auth-no-open-browser --config /data/rclone.conf`), stdout em modo linha via thread.
   - **client_id/client_secret (Avançado)**: quando ambos são informados no body de `/api/connect/start`, são passados como **argumentos positionais** a `rclone authorize <backend> <cid> <csec>` (ambos obrigatórios juntos, senão 400). Gravados como `client_id =` / `client_secret =` dentro da seção do provedor em `/data/rclone.conf` — **somente lá**, nunca em settings.json nem em respostas/logs.
2. Extrai a URL **com `state=`** do stdout (ignora o aviso de "Redirect URL") → **abre em nova aba do browser do usuário**.
3. Usuário loga → callback cai em `localhost:53682` do host → **proxy TCP interno** (`app/callback_proxy.py`, porta 53683 publicada) encaminha ao loopback do container onde o rclone escuta (docker publishing não alcança listeners de loopback do container).
4. O rclone imprime o token blob no stdout (seção `[drive]` etc.) → app captura, **normaliza o header para o nome do remote** (`[gdrive]`) e grava em `/data/rclone.conf` atomicamente (com `client_id =` / `client_secret =` quando houver credenciais customizadas).
5. UI verifica via `section_present` (file-based, sem subprocess por poll) → mostra ✅ Conectado ou erro.

Por provider:
- **gdrive**: client_id embutido do rclone funciona out-of-the-box, mas o client_id compartilhado será **aposentado em 2026** → a UI mostra a box "Avançado" para todos os provedores (label gdrive: "recomendado — … aposentado em 2026").
- **dropbox**: funciona out-of-the-box, mas o client embutido é compartilhado/rate-limited → a UI mostra campos **opcionalais "Avançado"** (`client_id`/`client_secret`) recomendados para uso pesado.
- **onedrive**: opcional.
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
      - "127.0.0.1:53682:53683"  # callback OAuth (proxy → loopback do container)
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
