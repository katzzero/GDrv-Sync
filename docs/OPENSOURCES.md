# Open-sources avaliados (pesquisa 2026-11-04)

Objetivo (v1): sync de **3 tarefas independentes — 1 pasta local por provedor (`/sync/Gdrive`, `/sync/Dropbox`, `/sync/Onedrive`) ↔ pasta escolhida na nuvem (ou raiz)**, com UI HTML (abas por provedor), intervalo fixo, dentro de Docker. Providers: gdrive, dropbox, onedrive (Box fora).

## Conclusão rápida

| Projeto | Licença | O que é | Veredito |
|---|---|---|---|
| [rclone](https://rclone.org) | MIT | CLI de sync p/ 70+ backends (incl. Google Drive, com `sync`, `bisync`, `lsd`, `rcd`/RPC) | **Base do projeto** |
| [rclone/rclone-web](https://github.com/rclone/rclone-web) (`rclone gui`) | MIT | Web GUI oficial embutida no rclone: remotes, explorer, transfers, docker-ready (portas 5522/5533) | **Reusável** — referência de UX; pesado p/ nosso caso 1-par-1-intervalo |
| [xzzpig/rclone-sync](https://github.com/xzzpig/rclone-sync) | MIT | Gerenciador estilo "Synology Cloud Sync": tarefas, upload/download/bidirecional, remote path picker, agendamento/real-time, logs, imagem Docker pronta | **Inspiração direta** — UX mais próxima do pedido; projeto novo (1★), não confiar cegamente |
| [rclone-ui/rclone-ui](https://github.com/rclone-ui/rclone-ui) | Apache-2.0 | GUI cross-platform (Tauri) sobre `rclone rcd` | Desktop-first; útil p/ ver como consomem a API RC |
| [gnasdev/gn-drive](https://github.com/gnasdev/gn-drive) | — | Go + Vue, loopback-only, perfis pull/push/bi-sync, cron, shell-out rclone | Bom modelo de arquitetura thin-wrapper; alpha |
| [Klomgor/rclone-docker](https://github.com/Klomgor/rclone-docker) | — | Docker rclone + WebGUI + cron sync + healthcheck | Referência de compose/entrypoint |
| [controlol/gdrive-rclone-docker](https://github.com/controlol/gdrive-rclone-docker) | MIT | Mount FUSE + push a cada 6h, crypt opcional | Modelo mount ≠ nosso requisito (sync puro, sem /dev/fuse) |

## Decisão: construir thin-wrapper próprio sobre rclone

Nenhum projeto entrega exatamente "um par de pastas, intervalo, UI simples, 1 container". Mas todos validam a peça central: **rclone como motor**. Nós escrevemos só a camada de UI/loop (~200 linhas) e reusamos:

1. **Motor de sync**: `rclone sync` (one-way) e `rclone bisync` (two-way) — comandos nativos, sem inventar nada.
2. **Picker de pastas do Drive**: `rclone lsd gdrive:/CAMINHO` (listagem de só-pastas, rápida) — mesma técnica do remote-path selector do xzzpig/rclone-sync.
3. **OAuth no HTML (Opção A)**: `rclone authorize <provider> --port 53682` em subprocess; a app captura a URL do stdout (redireciona o browser) e o token blob do stdout (grava em `rclone.conf`). Portas loopback são aceitas pelo client OAuth "desktop" do rclone. Fluxo válido para gdrive/onedrive/dropbox (v1; Box excluído por exigir app próprio). Alternativa documentada: API RC (`core/authorize-url` + `core/token`) rodando `rclone rcd`, como fazem rclone-web/rclone-ui.
4. **Imagem base oficial**: `rclone/rclone:latest` (ou `python:3.12-slim` + binário rclone estático baixado do release) — evita manter fork de imagem.
5. **Plano B de zero-código** (documentado no README, não construído): subir `rclone/rclone:latest gui --addr 0.0.0.0:5522 --api-addr 0.0.0.0:5533` + cron no host — para quem quiser a GUI oficial em vez da nossa UI enxuta.

## Riscos conhecidos (mitigados no plano)

- **Bisync do rclone**: exige paridade de estado (`--resync` na 1ª execução); estado em volume persistente. Não usar `--resync` recorrente.
- **Rate limits da API do Google**: intervalo mínimo recomendado ≥ 5 min; usar `--fast-list` quando aplicável (Drive: `--drive-skip-...`/trashed queries automáticas).
- **`rclone authorize` deprecated em favors de `rclone config` headless?** — o fluxo copy-free ainda funciona; fallback: guia de client_id próprio no README.
- **UI sem auth**: binds locais apenas; documentar para não expor na LAN sem reverse-proxy.
