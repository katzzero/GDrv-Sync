"""i18n for gdrv-sync WebUI.

Flat dictionary of keys -> strings for the two supported languages:
  * "pt" = Portuguese (Brazil) - default
  * "en" = English

Every user-visible string in the templates (server-rendered Jinja and
client JS-generated) and every user-facing API message lives here.  Keys
are intentionally descriptive and scoped by domain (nav/, header/,
settings/, connect/, status/, browse/, api/, ...).

Machine-readable error CODES (error:"confirm_required" etc.) are kept
UNTRANSLATED in main.py and are NOT part of this dictionary.
"""

LANGS = {
    "pt": {
        # ---- navigation (base.html) ----
        "nav_settings": "⚙ Configurações",
        "nav_connect": "🔑 Conectar",
        "nav_status": "📊 Status",
        "navsub_volumes": "Volumes",
        "vol_data": "./data → /data",
        "vol_sync": "LOCAL_SYNC_DIR → /sync",

        # provider labels (used by JS too)
        "prov_gdrive": "Google Drive",
        "prov_dropbox": "Dropbox",
        "prov_onedrive": "OneDrive",

        # provider advanced-box notes (localized)
        "prov_gdrive_client_id_note": "recomendado — o client_id compartilhado do rclone será aposentado em 2026",
        "prov_gdrive_redirect_note": "Registre no app do Google: http://localhost:53682/ e http://127.0.0.1:53682/",
        "prov_gdrive_help_where": "console.cloud.google.com",
        "prov_gdrive_help_steps_0": "Crie (ou reutilize) um projeto no Google Cloud",
        "prov_gdrive_help_steps_1": "Ative a API “Google Drive API”",
        "prov_gdrive_help_steps_2": "Configure a tela de consentimento OAuth (External) e crie um credencial “OAuth Client ID” tipo “Desktop app”",
        "prov_gdrive_help_steps_3": "Cole o client_id e o client_secret aqui e clique Conectar",
        "prov_gdrive_help_docs_label": "guia completo do rclone",
        "prov_gdrive_help_note": "apps Google “não verificados” limitam a ~100 usuários; para uso pessoal isso é irrelevante.",

        "prov_dropbox_client_id_note": "opcional; recomendado em uso pesado — evita rate-limit do client compartilhado do rclone",
        "prov_dropbox_redirect_note": "Adicione no app do Dropbox as redirect URIs http://localhost:53682/ e http://127.0.0.1:53682/",
        "prov_dropbox_help_where": "dropbox.com/developers/apps",
        "prov_dropbox_help_steps_0": "Crie um app “Dropbox API” com escopo “Full content”",
        "prov_dropbox_help_steps_1": "Copie a “App key” (client_id) e a “App secret” (client_secret)",
        "prov_dropbox_help_steps_2": "Em “OAuth2”, adicione as redirect URIs localhost/127.0.0.1:53682",
        "prov_dropbox_help_steps_3": "Cole aqui e clique Conectar",
        "prov_dropbox_help_docs_label": "configuração Dropbox do rclone",
        "prov_dropbox_help_note": "",

        "prov_onedrive_client_id_note": "opcional",
        "prov_onedrive_redirect_note": "Em “Redirecionar URI” adicione http://localhost:53682/ e http://127.0.0.1:53682/",
        "prov_onedrive_help_where": "portal.azure.com → Azure Active Directory",
        "prov_onedrive_help_steps_0": "App registrations → New registration (qualquer conta)",
        "prov_onedrive_help_steps_1": "Em “Authentication”, adicione as redirect URIs públicas localhost/127.0.0.1:53682",
        "prov_onedrive_help_steps_2": "Certificates & secrets → crie um client secret",
        "prov_onedrive_help_steps_3": "Cole o Application (client) ID e o secret aqui e clique Conectar",
        "prov_onedrive_help_docs_label": "configuração OneDrive do rclone",
        "prov_onedrive_help_note": "o client compartilhado do rclone segue funcionando; o próprio é opcional.",

        # ---- header / badges (base.html) ----
        "lang_label": "Idioma:",
        "lang_pt": "PT",
        "lang_en": "EN",
        "header_healthy": "container: saudável",
        "header_degraded": "container: degradado",
        "healthz_title": "GET /healthz",
        "badge_connected": "✓ conectado",
        "badge_disconnected": "não conectado",

        # ---- settings page ----
        "settings_title": "Configurações por provedor",
        "settings_sub": "Cada aba tem sua tarefa própria: pasta local fixa em <code>/sync/&lt;Provedor&gt;</code> (criada automaticamente) ↔ pasta escolhida na nuvem.",
        "conn_authenticated": "✓ <code>{provider}</code> autenticado",
        "conn_not_authenticated": "✗ <code>{provider}</code> não autenticado",
        "btn_reconnect": "Reconectar",
        "btn_connect": "🔗 Conectar",
        "btn_connected": "Conectado",

        "dir_upload_label": "⬆︎ Upload — local → nuvem (nunca apaga na nuvem)",
        "dir_upload_note": "Copia para a nuvem. Nunca apaga nada na nuvem (não destrutivo por padrão).",
        "dir_download_label": "⬇︎ Download — nuvem → local (nunca apaga no local)",
        "dir_download_note": "Copia para o local. Nunca apaga nada no local (não destrutivo por padrão).",
        "dir_bisync_label": "⇄ Bidirecional — DESTRUTIVO: propaga deleções",
        "dir_bisync_note": "Atenção: bisync propaga exclusões nos dois lados (apagar num lado apaga no outro). Conflito de conteúdo = aborta (--conflict-resolve none). Para só copiar sem apagar nada, use Upload/Download.",

        "label_local_folder": "Pasta local (dentro de /sync)",
        "local_folder_help": "Criada automaticamente no volume LOCAL_SYNC_DIR. Padrão: uma por provedor (independentes). <b>Hub:</b> use o MESMO nome em várias abas para copiar a mesma pasta para todas as nuvens selecionadas{edit_note}.",
        "label_cloud_folder": "Pasta na nuvem",
        "btn_browse": "📁 Navegar",
        "btn_dedicated": "📦 Criar/usar pasta dedicada \"{dedicated}\"",
        "cloud_root": "Vazio (<code>{provider}:</code>) = raiz do provedor — evite (todo o Drive vira destino).",
        "cloud_root_upload_where": "pasta na RAIZ da nuvem, irmã do destino — nunca dentro dele",
        "cloud_root_download_where": "lado local, visível no volume ./data",
        "root_danger_strong": "⚠ Perigo",
        "root_danger_remote": "remoto é a raiz do provedor (<code>{provider}:</code>)",
        "root_danger_body": "Com espelho+upload, <em>todo</em> o conteúdo da nuvem se torna destino e arquivos extras são movidos para o backup-dir na nuvem.",
        "local_hub_edit_note": " (edite desabilitando a tarefa)",

        "label_direction": "Direção",
        "mirror_not_allowed_bisync": "Modo espelho não é permitido em direção Bidirecional.",
        "label_mirror": "Modo espelho (pode apagar no destino)",
        "mirror_active": "⚠️ <strong>Modo espelho ativo:</strong> arquivos que existem no destino mas não na origem serão <strong>movidos</strong> (não apagados) para o backup-dir: {where}",
        "mirror_confirm_label": "Entendo e quero ativar (obrigatório para salvar com espelho)",

        "label_interval": "Intervalo (min) — mínimo recomendado 5",
        "label_sync_enabled": "Sync habilitado",
        "connect_first": "Conecte a nuvem primeiro para habilitar.",
        "btn_save": "Salvar",
        "btn_preview": "🔍 Prévia (dry-run)",

        "warn_not_auth": "🔑 <code>{provider}</code> não está autenticado — habilite apenas após conectar (aba \"Conectar Nuvem\").",

        "preview_title": "🔍 Prévia (dry-run — nada é alterado)",
        "preview_deletions_note": "⚠ Há {n} deleção(ões) prevista(s). Com espelho ativo, estas vão para o backup-dir (não são apagadas de verdade). Sem espelho, cópia nunca deleta.",
        "preview_effective_cmd": "Comando efetivo (preview)",

        "alert_mirror_confirm": "Marque \"Entendo e quero ativar\" antes de salvar com Modo espelho.",
        "alert_connect_first": "Conecte {label} primeiro antes de habilitar o sync.",
        "alert_save_fail": "Falha ao salvar",
        "alert_network_save": "Erro de rede ao salvar",

        "preview_running": "Rodando prévia (dry-run)…",
        "preview_blocked_root": "⛔ Espelho + upload para a RAIZ do provedor é bloqueado. Escolha uma subpasta.",
        "preview_blocked_bisync": "⛔ Espelho não é permitido na direção Bidirecional.",
        "preview_unavailable": "⛔ Prévia indisponível: {error}",
        "preview_counts": "{n} cópias · {m} deleções",
        "preview_rc": "⚠ rclone rc={rc}",
        "preview_error": "Erro ao gerar prévia: {error}",

        "btn_creating": "Criando…",
        "ded_created": "✅ Pasta dedicada criada/selecionada: {remote}",
        "ded_warning_exists": "⚠ A pasta '{dedicated}' já existia e CONTÉM dados. Revise antes de habilitar Bidirecional ou Espelho — podem alterá-la/apagá-la.",
        "ded_warning_unchecked": "⚠ Não foi possível verificar se '{dedicated}' já tinha conteúdo. Confira na UI antes de habilitar modos destrutivos.",
        "ded_network_error": "⛔ Erro de rede: {error}",

        # ---- connect page ----
        "connect_title": "Conectar Nuvem",
        "connect_sub": "OAuth no seu navegador — nenhum copiar/colar. Cada provedor conecta de forma independente.",
        "badge_connected_short": "✓ conectado",
        "badge_disconnected_short": "não conectado",

        "advanced": "Avançado — client_id / client_secret próprios",
        "help_title": "📖 Como obter suas credenciais ({where})",
        "reference": "Referência:",
        "stored_note": "Gravados somente em /data/rclone.conf (volume), nunca em settings.json.",
        "placeholder_client_id": "client_id",
        "placeholder_client_secret": "client_secret",

        "step_authorize": "Inicia `rclone authorize {rclone_type}` no container (com client_id/secret quando preenchidos)",
        "step_open_login": "Abre o login do {label} no navegador (callback → localhost:53682)",
        "step_authorize_access": "Você autoriza o acesso",
        "step_token_saved": "Token capturado e gravado em /data/rclone.conf (seção {provider})",
        "step_validate": "Valida com `rclone lsd {provider}:`",

        "ok_connected": "✅ {label} conectado.",

        "redirect_note": "URIs de redirect a registrar no seu app OAuth (Google Cloud Console → credenciais → cliente desktop):",
        "redirect_uris": "http://localhost:53682/  e  http://127.0.0.1:53682/",
        "rclone_docs_link": "rclone: making your own client ID",

        "js_connecting": "Conectando…",
        "js_cannot_start_auth": "Não foi possível iniciar a autorização",
        "js_network_start": "Erro de rede ao iniciar a autorização",
        "js_timeout_cancel": "{provider}: a autorização excedeu o tempo limite e foi cancelada.",
        "js_auth_error": "erro na autorização",
        "js_auth_link": "link de autorização",
        "js_open_link": "Abra este link para autorizar: ",

        # ---- status page ----
        "status_title": "Últimas execuções",
        "status_sub": "agendador: 1 comando por vez · /healthz a cada 30s",
        "btn_run_now": "▶ Run now",
        "col_start": "Início",
        "col_provider": "Provedor",
        "col_direction": "Direção",
        "col_status": "Status",
        "col_files": "Arquivos",
        "col_duration": "Duração",
        "no_runs": "Nenhuma execução ainda.",

        "status_log_title": "Log (rclone)",
        "status_log_sub": "tail de /data/logs/sync-<provider>-<ts>.log",

        # ---- browse page ----
        "browse_title": "Selecionar pasta — {provider}",
        "browse_sub": "Somente pastas. Clique para entrar; use Selecionar esta pasta para escolher a mostrada no caminho abaixo.",
        "browse_not_auth": "⚠️ {provider} não está autenticado. Conecte-o primeiro em Conectar Nuvem.",
        "browse_root": "🏠 raiz ({provider})",
        "browse_root_provider": "🏠 raiz do provedor ({provider}:)",
        "browse_no_folders": "Nenhuma pasta encontrada.",
        "browse_connect_first": "Conecte a nuvem primeiro para listar pastas.",
        "btn_select_here": "Selecionar esta pasta",
        "browse_sel_label": "{provider}:{path}",
        "browse_loading": "Carregando…",

        # ---- API user-facing messages ----
        "api_confirm_required": "Ative a confirmação 'Entendo e quero ativar' antes de salvar o modo espelho.",
        "api_mirror_not_allowed_bisync": "Modo espelho não é permitido em direção Bidirecional.",
        "api_mirror_root_not_allowed": "Modo espelho com upload para a RAIZ do provedor é bloqueado (toda a nuvem seria destino e o backup sobreporia o destino). Escolha uma subpasta.",
        "api_not_authenticated": "Não é possível habilitar {provider}: remoto não autenticado. Conecte primeiro (Conectar Nuvem).",
        "api_invalid_remote": "Remoto inválido para {provider}: {remote}. Deixe vazio para a raiz do provedor, ou use '{provider}:/caminho'.",
        "api_interval_not_int": "interval_min deve ser um inteiro >= 5, obtido {value}.",
        "api_interval_too_low": "interval_min deve ser >= 5, obtido {value}.",
        "api_invalid_direction": "direction deve ser um de upload/download/bisync, obtido {value}.",
        "api_invalid_local_sub": "pasta local deve ter 1-64 chars: letras/dígitos/espaço/_/-, começando com alnum; sem '/' ou '..' (ex. 'Gdrive').",
        "api_ded_remote_set": "o remoto atual é '{remote}'; a pasta dedicada só é sugerida quando o destino é a raiz.",
        "api_ded_task_enabled": "desabilite a tarefa antes de trocar o destino para a pasta dedicada.",
        "api_ded_not_connected": "conecte o provedor primeiro.",
        "api_ded_mkdir_failed": "rclone mkdir falhou (escopo sem permissão de escrita?)",
        "api_ded_exists": "A pasta '{dedicated}' já existia e CONTÉM dados. Revise antes de habilitar Bidirecional ou Espelho — podem alterá-la/apagá-la.",
        "api_ded_unchecked": "Não foi possível verificar se '{dedicated}' já tinha conteúdo. Confira na UI antes de habilitar modos destrutivos.",
        "api_both_required": "client_id e client_secret devem ser informados juntos (Avançado).",
        "api_auth_url_fail": "Não foi possível obter URL de autorização",
        "api_auth_no_token": "authorize terminou sem um token",
        "api_run_now": "Execução enfileirada para {provider}",
        "api_cancelled": "Cancelado",
        "bisync_first_run_note": "(1ª exec/ após queda: --resync)",
        "healthz_rclone_missing": "binário rclone não encontrado",
        "healthz_failures": "{provider} tem 3+ falhas consecutivas",
        "api_invalid_provider": "Provedor desconhecido: {provider}. Permitidos: {allowed}.",
    },
    "en": {
        # ---- navigation (base.html) ----
        "nav_settings": "⚙ Settings",
        "nav_connect": "🔑 Connect",
        "nav_status": "📊 Status",
        "navsub_volumes": "Volumes",
        "vol_data": "./data → /data",
        "vol_sync": "LOCAL_SYNC_DIR → /sync",

        # provider labels (used by JS too)
        "prov_gdrive": "Google Drive",
        "prov_dropbox": "Dropbox",
        "prov_onedrive": "OneDrive",

        # provider advanced-box notes (localized)
        "prov_gdrive_client_id_note": "recommended — the shared rclone client_id will be retired in 2026",
        "prov_gdrive_redirect_note": "Register in your Google app: http://localhost:53682/ and http://127.0.0.1:53682/",
        "prov_gdrive_help_where": "console.cloud.google.com",
        "prov_gdrive_help_steps_0": "Create (or reuse) a Google Cloud project",
        "prov_gdrive_help_steps_1": "Enable the “Google Drive API”",
        "prov_gdrive_help_steps_2": "Configure the OAuth consent screen (External) and create an “OAuth Client ID” of type “Desktop app”",
        "prov_gdrive_help_steps_3": "Paste the client_id and client_secret here and click Connect",
        "prov_gdrive_help_docs_label": "full rclone guide",
        "prov_gdrive_help_note": "Google “unverified” apps are limited to ~100 users; for personal use this is irrelevant.",

        "prov_dropbox_client_id_note": "optional; recommended for heavy use — avoids the shared rclone client rate-limit",
        "prov_dropbox_redirect_note": "Add to your Dropbox app the redirect URIs http://localhost:53682/ and http://127.0.0.1:53682/",
        "prov_dropbox_help_where": "dropbox.com/developers/apps",
        "prov_dropbox_help_steps_0": "Create a “Dropbox API” app with “Full content” scope",
        "prov_dropbox_help_steps_1": "Copy the “App key” (client_id) and the “App secret” (client_secret)",
        "prov_dropbox_help_steps_2": "In “OAuth2”, add the redirect URIs localhost/127.0.0.1:53682",
        "prov_dropbox_help_steps_3": "Paste here and click Connect",
        "prov_dropbox_help_docs_label": "rclone Dropbox setup",
        "prov_dropbox_help_note": "",

        "prov_onedrive_client_id_note": "optional",
        "prov_onedrive_redirect_note": "In “Redirect URI” add http://localhost:53682/ and http://127.0.0.1:53682/",
        "prov_onedrive_help_where": "portal.azure.com → Azure Active Directory",
        "prov_onedrive_help_steps_0": "App registrations → New registration (any account)",
        "prov_onedrive_help_steps_1": "In “Authentication”, add the public redirect URIs localhost/127.0.0.1:53682",
        "prov_onedrive_help_steps_2": "Certificates & secrets → create a client secret",
        "prov_onedrive_help_steps_3": "Paste the Application (client) ID and the secret here and click Connect",
        "prov_onedrive_help_docs_label": "rclone OneDrive setup",
        "prov_onedrive_help_note": "the shared rclone client keeps working; your own is optional.",

        # ---- header / badges (base.html) ----
        "lang_label": "Language:",
        "lang_pt": "PT",
        "lang_en": "EN",
        "header_healthy": "container: healthy",
        "header_degraded": "container: degraded",
        "healthz_title": "GET /healthz",
        "badge_connected": "✓ connected",
        "badge_disconnected": "not connected",

        # ---- settings page ----
        "settings_title": "Settings per provider",
        "settings_sub": "Each tab has its own task: fixed local folder in /sync/<Provider> (created automatically) ↔ cloud folder of your choice.",
        "conn_authenticated": "✓ <code>{provider}</code> authenticated",
        "conn_not_authenticated": "✗ <code>{provider}</code> not authenticated",
        "btn_reconnect": "Reconnect",
        "btn_connect": "🔗 Connect",
        "btn_connected": "Connected",

        "dir_upload_label": "⬆︎ Upload — local → cloud (never deletes in cloud)",
        "dir_upload_note": "Copies to the cloud. Never deletes anything in the cloud (non-destructive by default).",
        "dir_download_label": "⬇︎ Download — cloud → local (never deletes locally)",
        "dir_download_note": "Copies to local. Never deletes anything locally (non-destructive by default).",
        "dir_bisync_label": "⇄ Bidirectional — DESTRUCTIVE: propagates deletions",
        "dir_bisync_note": "Warning: bidirectional sync propagates deletions on both sides (deleting on one side deletes on the other). Content conflict = aborts (--conflict-resolve none). To only copy without deleting anything, use Upload/Download.",

        "label_local_folder": "Local folder (inside /sync)",
        "local_folder_help": "Created automatically in the LOCAL_SYNC_DIR volume. Default: one per provider (independent). <b>Hub:</b> use the SAME name in several tabs to copy the same folder to all selected clouds{edit_note}.",
        "label_cloud_folder": "Cloud folder",
        "btn_browse": "📁 Browse",
        "btn_dedicated": "📦 Create/use dedicated folder \"{dedicated}\"",
        "cloud_root": "Empty (<code>{provider}:</code>) = provider root — avoid (the whole Drive becomes the destination).",
        "cloud_root_upload_where": "folder at the cloud ROOT, a sibling of the destination — never inside it",
        "cloud_root_download_where": "local side, visible in the ./data volume",
        "root_danger_strong": "⚠ Danger",
        "root_danger_remote": "remote is the provider root (<code>{provider}:</code>)",
        "root_danger_body": "With mirror+upload, <em>all</em> cloud content becomes the destination and extra files are moved to the backup-dir in the cloud.",
        "local_hub_edit_note": " (edit by disabling the task)",

        "label_direction": "Direction",
        "mirror_not_allowed_bisync": "Mirror mode is not allowed in Bidirectional direction.",
        "label_mirror": "Mirror mode (may delete in destination)",
        "mirror_active": "⚠️ <strong>Mirror mode active:</strong> files that exist in the destination but not in the source will be <strong>moved</strong> (not deleted) to the backup-dir: {where}",
        "mirror_confirm_label": "I understand and want to enable (required to save with mirror)",

        "label_interval": "Interval (min) — recommended minimum 5",
        "label_sync_enabled": "Sync enabled",
        "connect_first": "Connect the cloud first to enable.",
        "btn_save": "Save",
        "btn_preview": "🔍 Preview (dry-run)",

        "warn_not_auth": "🔑 <code>{provider}</code> is not authenticated — enable only after connecting (Connect Cloud tab).",

        "preview_title": "🔍 Preview (dry-run — nothing is changed)",
        "preview_deletions_note": "⚠ There are {n} predicted deletion(s). With mirror active, these go to the backup-dir (not truly deleted). Without mirror, copy never deletes.",
        "preview_effective_cmd": "Effective command (preview)",

        "alert_mirror_confirm": "Check \"I understand and want to enable\" before saving with Mirror mode.",
        "alert_connect_first": "Connect {label} first before enabling sync.",
        "alert_save_fail": "Failed to save",
        "alert_network_save": "Network error saving",

        "preview_running": "Running preview (dry-run)…",
        "preview_blocked_root": "⛔ Mirror + upload to the provider ROOT is blocked. Choose a subfolder.",
        "preview_blocked_bisync": "⛔ Mirror is not allowed in the Bidirectional direction.",
        "preview_unavailable": "⛔ Preview unavailable: {error}",
        "preview_counts": "{n} copies · {m} deletions",
        "preview_rc": "⚠ rclone rc={rc}",
        "preview_error": "Error generating preview: {error}",

        "btn_creating": "Creating…",
        "ded_created": "✅ Dedicated folder created/selected: {remote}",
        "ded_warning_exists": "⚠ The folder '{dedicated}' already existed and CONTAINS data. Review before enabling Bidirectional or Mirror — they may modify/delete it.",
        "ded_warning_unchecked": "⚠ Could not verify whether '{dedicated}' already had content. Check in the UI before enabling destructive modes.",
        "ded_network_error": "⛔ Network error: {error}",

        # ---- connect page ----
        "connect_title": "Connect Cloud",
        "connect_sub": "OAuth in your browser — no copy/paste. Each provider connects independently.",
        "badge_connected_short": "✓ connected",
        "badge_disconnected_short": "not connected",

        "advanced": "Advanced — your own client_id / client_secret",
        "help_title": "📖 How to get your credentials ({where})",
        "reference": "Reference:",
        "stored_note": "Stored only in /data/rclone.conf (volume), never in settings.json.",
        "placeholder_client_id": "client_id",
        "placeholder_client_secret": "client_secret",

        "step_authorize": "Start `rclone authorize {rclone_type}` in the container (with client_id/secret when filled)",
        "step_open_login": "Open the {label} login in the browser (callback → localhost:53682)",
        "step_authorize_access": "You authorize access",
        "step_token_saved": "Token captured and saved to /data/rclone.conf (section {provider})",
        "step_validate": "Validate with `rclone lsd {provider}:`",

        "ok_connected": "✅ {label} connected.",

        "redirect_note": "Redirect URIs to register in your OAuth app (Google Cloud Console → credentials → desktop client):",
        "redirect_uris": "http://localhost:53682/  and  http://127.0.0.1:53682/",
        "rclone_docs_link": "rclone: making your own client ID",

        "js_connecting": "Connecting…",
        "js_cannot_start_auth": "Could not start authorization",
        "js_network_start": "Network error starting authorization",
        "js_timeout_cancel": "{provider}: authorization exceeded the time limit and was cancelled.",
        "js_auth_error": "authorization error",
        "js_auth_link": "authorization link",
        "js_open_link": "Open this link to authorize: ",

        # ---- status page ----
        "status_title": "Latest runs",
        "status_sub": "scheduler: 1 command at a time · /healthz every 30s",
        "btn_run_now": "▶ Run now",
        "col_start": "Start",
        "col_provider": "Provider",
        "col_direction": "Direction",
        "col_status": "Status",
        "col_files": "Files",
        "col_duration": "Duration",
        "no_runs": "No runs yet.",

        "status_log_title": "Log (rclone)",
        "status_log_sub": "tail of /data/logs/sync-<provider>-<ts>.log",

        # ---- browse page ----
        "browse_title": "Select folder — {provider}",
        "browse_sub": "Folders only. Click to enter; use Select this folder to choose the one shown in the path below.",
        "browse_not_auth": "⚠️ {provider} is not authenticated. Connect it first in Connect Cloud.",
        "browse_root": "🏠 root ({provider})",
        "browse_root_provider": "🏠 provider root ({provider}:)",
        "browse_no_folders": "No folders found.",
        "browse_connect_first": "Connect the cloud first to list folders.",
        "btn_select_here": "Select this folder",
        "browse_sel_label": "{provider}:{path}",
        "browse_loading": "Loading…",

        # ---- API user-facing messages ----
        "api_confirm_required": "Enable the 'I understand and want to enable' confirmation before saving mirror mode.",
        "api_mirror_not_allowed_bisync": "Mirror mode is not allowed in Bidirectional direction.",
        "api_mirror_root_not_allowed": "Mirror mode with upload to the provider ROOT is blocked (the whole cloud would be the destination and the backup would overlap the destination). Choose a subfolder.",
        "api_not_authenticated": "Cannot enable {provider}: remote not authenticated. Connect it first (Connect Cloud).",
        "api_invalid_remote": "Invalid remote for {provider}: {remote}. Leave empty for provider root, or use '{provider}:/path'.",
        "api_interval_not_int": "interval_min must be an integer >= 5, got {value}.",
        "api_interval_too_low": "interval_min must be >= 5, got {value}.",
        "api_invalid_direction": "direction must be one of upload/download/bisync, got {value}.",
        "api_invalid_local_sub": "local folder must be 1-64 chars: letters/digits/space/_/-, starting with alnum; no '/' or '..' (e.g. 'Gdrive').",
        "api_ded_remote_set": "remote currently is '{remote}'; the dedicated folder is only suggested when the destination is the root.",
        "api_ded_task_enabled": "disable the task before switching the destination to the dedicated folder.",
        "api_ded_not_connected": "connect the provider first.",
        "api_ded_mkdir_failed": "rclone mkdir failed (write permission scope?)",
        "api_ded_exists": "The folder '{dedicated}' already existed and CONTAINS data. Review before enabling Bidirectional or Mirror — they may modify/delete it.",
        "api_ded_unchecked": "Could not verify whether '{dedicated}' already had content. Check in the UI before enabling destructive modes.",
        "api_both_required": "client_id and client_secret must be provided together (Advanced).",
        "api_auth_url_fail": "Could not get auth URL",
        "api_auth_no_token": "authorize ended without a token",
        "api_run_now": "Run enqueued for {provider}",
        "api_cancelled": "Cancelled",
        "bisync_first_run_note": "(1st run / after interruption: --resync)",
        "healthz_rclone_missing": "rclone binary not found",
        "healthz_failures": "{provider} has 3+ consecutive failures",
        "api_invalid_provider": "Unknown provider: {provider}. Allowed: {allowed}.",
    },
}


def get_lang(request) -> str:
    """Resolve the UI language for a request.

    Priority: cookie "gdrv_lang" ("pt"|"en") → Accept-Language header
    starting with "en" → "en" : "pt" default.
    """
    cookie = request.cookies.get("gdrv_lang")
    if cookie in ("pt", "en"):
        return cookie
    accept = request.headers.get("accept-language", "")
    if accept.lower().startswith("en"):
        return "en"
    return "pt"


def t(key: str, lang: str) -> str:
    """Translate a key for the given language.

    Falls back to "pt", then returns the key itself if missing
    (KeyError-safe, never raises).
    """
    strings = LANGS.get(lang) or LANGS["pt"]
    if key in strings:
        return strings[key]
    if lang != "pt" and key in LANGS["pt"]:
        return LANGS["pt"][key]
    return key
