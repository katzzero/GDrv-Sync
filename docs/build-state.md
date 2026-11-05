# Estado da build — gdrv-sync v1 (2026-11-04)

**Nota histórica:** Este projeto iniciou como "gd-sync" e foi renomeado para "gdrv-sync" na tag v0.0.1.

## Status
APROVADO pelo supervisor. Não commitado no git (aguardando decisão do usuário).

## Entregue
Docker + FastAPI + rclone num único container; 3 tarefas independentes (Google Drive, Dropbox, OneDrive Personal), cada uma com aba própria na UI, pasta local fixa (/sync/Gdrive, /sync/Dropbox, /sync/Onedrive, definida pelo volume LOCAL_SYNC_DIR do compose), direção por tarefa (upload/download/bisync com 1ª execução --resync), intervalo por tarefa (>=5 min), picker de pastas do provedor com raiz selecionável, OAuth "dentro do HTML" via rclone authorize (porta loopback 53682), /healthz agregando connected/enabled por provedor, scheduler com lock de execução separado dos leitores, backoff exponencial, marker de interrupção de bisync, container non-root, UI em 127.0.0.1:8080.

## Pipeline de qualidade
builder S1 (v1) → auditoria/correções builder S5 (120B) → fix do wiring de persistência do token OAuth → cadeia de review paralelo 4 revisores (qwen S1 / bonsai S2 / nemotron S3 / laguna S4) → calibrador gemma4-31b (21 confirmados, 4 contestados) → fix pass completo (C1,C2,H1-H5,M1-M17,L1-L5) → re-review direcionado (22/22 corrigidos) → micro-fix da regressão running-flag + 2 hardenings → smoke test final.

## Riscos conhecidos
fluxo OAuth não testado end-to-end com contas reais (persistência do token testada offline com binário fake; nota honesta no README); ./data do host precisa ser gravável pelo uid 1000; provider habilitado no primeiro boot espera o 1º tick de reload (ou Run now); Box e OneDrive Business fora da v1 (documentados no PLANO).

## Verificação (reproduzível)
python3 -m py_compile app/*.py; docker-compose config; docker build -t gdrv-sync .; docker-compose up -d; curl localhost:8080/healthz (shape PLANO §8); POST /api/settings com remote=/etc → 400; /browse?provider=evil → 400; remote "gdrive:" (raiz) → 200; /healthz responde em <10ms; 0 exceções no log; docker-compose down.