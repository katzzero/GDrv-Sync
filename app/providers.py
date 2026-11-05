"""Static metadata for cloud providers."""

PROVIDERS = {
    "gdrive": {
        "label": "Google Drive",
        "local_sub": "Gdrive",
        "rclone_type": "drive",
        "root_label": "raiz do Meu Drive",
        "needs_client_id": False,
    },
    "dropbox": {
        "label": "Dropbox",
        "local_sub": "Dropbox",
        "rclone_type": "dropbox",
        "root_label": "raiz do Dropbox (app rclone)",
        "needs_client_id": True,
    },
    "onedrive": {
        "label": "OneDrive",
        "local_sub": "Onedrive",
        "rclone_type": "onedrive",
        "root_label": "raiz do OneDrive",
        "needs_client_id": False,
    },
}

DEFAULT_INTERVAL_MIN = 5
MAX_LOG_ENTRIES = 50