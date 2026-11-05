"""Static metadata for cloud providers."""

# Dedicated cloud folder the UI offers to create/use on connect
# (sandbox for any future destructive op; see docs/PLANO.md §6a).
DEDICATED_FOLDER = "GDrv-Folder"

PROVIDERS = {
    "gdrive": {
        "label": "Google Drive",
        "local_sub": "Gdrive",
        "rclone_type": "drive",
        "root_label": "raiz do Meu Drive",
        "needs_client_id": False,
        # client_id próprio vira recomendado em 2026 (aposentadoria do client_id
        # compartilhado do rclone). Redirect URIs a registrar na nuvem:
        # http://localhost:53682/ e http://127.0.0.1:53682/
        "client_id_note": "recomendado — o client_id compartilhado do rclone será aposentado em 2026",
        "redirect_note": "Registre no app do Google: http://localhost:53682/ e http://127.0.0.1:53682/",
        "client_help": {
            "where": "console.cloud.google.com",
            "steps": [
                "Crie (ou reutilize) um projeto no Google Cloud",
                "Ative a API “Google Drive API”",
                "Configure a tela de consentimento OAuth (External) e crie um credencial “OAuth Client ID” tipo “Desktop app”",
                "Cole o client_id e o client_secret aqui e clique Conectar",
            ],
            "docs_url": "https://rclone.org/drive/#making-your-own-client-id",
            "docs_label": "guia completo do rclone",
            "note": "apps Google “não verificados” limitam a ~100 usuários; para uso pessoal isso é irrelevante.",
        },
    },
    "dropbox": {
        "label": "Dropbox",
        "local_sub": "Dropbox",
        "rclone_type": "dropbox",
        "root_label": "raiz do Dropbox (app rclone)",
        "needs_client_id": True,
        "client_id_note": "opcional; recomendado em uso pesado — evita rate-limit do client compartilhado do rclone",
        "redirect_note": "Adicione no app do Dropbox as redirect URIs http://localhost:53682/ e http://127.0.0.1:53682/",
        "client_help": {
            "where": "dropbox.com/developers/apps",
            "steps": [
                "Crie um app “Dropbox API” com escopo “Full content”",
                "Copie a “App key” (client_id) e a “App secret” (client_secret)",
                "Em “OAuth2”, adicione as redirect URIs localhost/127.0.0.1:53682",
                "Cole aqui e clique Conectar",
            ],
            "docs_url": "https://rclone.org/dropbox/",
            "docs_label": "configuração Dropbox do rclone",
            "note": "",
        },
    },
    "onedrive": {
        "label": "OneDrive",
        "local_sub": "Onedrive",
        "rclone_type": "onedrive",
        "root_label": "raiz do OneDrive",
        "needs_client_id": False,
        "client_id_note": "opcional",
        "redirect_note": "Em “Redirecionar URI” adicione http://localhost:53682/ e http://127.0.0.1:53682/",
        "client_help": {
            "where": "portal.azure.com → Azure Active Directory",
            "steps": [
                "App registrations → New registration (qualquer conta)",
                "Em “Authentication”, adicione as redirect URIs públicas localhost/127.0.0.1:53682",
                "Certificates & secrets → crie um client secret",
                "Cole o Application (client) ID e o secret aqui e clique Conectar",
            ],
            "docs_url": "https://rclone.org/onedrive/",
            "docs_label": "configuração OneDrive do rclone",
            "note": "o client compartilhado do rclone segue funcionando; o próprio é opcional.",
        },
    },
}

DEFAULT_INTERVAL_MIN = 5
MAX_LOG_ENTRIES = 50