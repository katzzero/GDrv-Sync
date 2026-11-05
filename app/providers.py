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
    },
    "dropbox": {
        "label": "Dropbox",
        "local_sub": "Dropbox",
        "rclone_type": "dropbox",
        "root_label": "raiz do Dropbox (app rclone)",
        "needs_client_id": True,
        "client_id_note": "opcional; recomendado em uso pesado — evita rate-limit do client compartilhado do rclone",
        "redirect_note": "",
    },
    "onedrive": {
        "label": "OneDrive",
        "local_sub": "Onedrive",
        "rclone_type": "onedrive",
        "root_label": "raiz do OneDrive",
        "needs_client_id": False,
        "client_id_note": "opcional",
        "redirect_note": "",
    },
}

DEFAULT_INTERVAL_MIN = 5
MAX_LOG_ENTRIES = 50