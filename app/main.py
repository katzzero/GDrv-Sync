"""Main FastAPI application."""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from .providers import PROVIDERS, DEDICATED_FOLDER
from .rclone_ops import (
    version as rclone_version,
    lsd, check_connected, ensure_dirs, section_present, invalidate_section_cache,
    RCLONE_CONF, LOGS_DIR, DATA_DIR, SYNC_DIR,
    authorize_start, authorize_finish, authorize_cancel, authorize_remove, write_rclone_section,
    get_authorize_session,
    preview, mkdir_remote, remote_is_empty,
)
from .callback_proxy import start_callback_proxy
from .scheduler import scheduler, SETTINGS_PATH

app = FastAPI()
log = logging.getLogger("gdrv-sync")

# Templates path relative to this module file (works in-container /app/app and
# locally when running from the repo root).
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Cached rclone version (computed once at startup; avoids a subprocess on every
# /healthz and page render) (M5).
_RCLONE_VERSION_CACHE: Optional[str] = None


def load_settings() -> Dict[str, Any]:
    """Load /data/settings.json (honors DATA_DIR via SETTINGS_PATH)."""
    if not SETTINGS_PATH.exists():
        return scheduler.get_settings()
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return scheduler.get_settings()


def save_settings_atomic(settings: Dict[str, Any]) -> None:
    """Atomically write settings.json (tmp + rename) and refresh scheduler cache."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(tmp_path, SETTINGS_PATH)
    # Signal scheduler to reload on next tick (mtime will differ).
    scheduler._reload_settings_if_changed()


def validate_provider(provider: Optional[str]) -> str:
    """Validate provider against the 3 allowed values; raise 400 otherwise."""
    if provider not in PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider: {provider!r}. Allowed: {sorted(PROVIDERS)}",
        )
    return provider


def normalize_remote(provider: str, remote: Optional[str]) -> str:
    """Normalize a remote value: empty -> provider root; must start with f'{provider}:'.

    Returns the normalized value, or raises HTTPException(400) for unsafe values
    (H2: colon-less or absolute-path-looking remotes would be treated as local
    paths by rclone).
    """
    if remote is None:
        remote = ""
    remote = remote.strip()
    if remote == "":
        return f"{provider}:"
    prefix = f"{provider}:"
    if remote.startswith(prefix):
        return remote
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            f"Invalid remote for {provider}: {remote!r}. "
            f"Leave empty for provider root, or use '{prefix}/path'."
        ),
    )


def parse_interval(value: Any) -> int:
    """Parse interval_min; raise HTTPException(400) on non-int (L2)."""
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"interval_min must be an integer >= 5, got {value!r}",
        )
    if iv < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"interval_min must be >= 5, got {iv}",
        )
    return iv


def parse_local_sub(value: Any, provider: str) -> str:
    """Validate a configurable per-provider local folder name (hub/independent).

    Safe ASCII names only: no '/', no '..', cannot start with '.', max 64 chars.
    Default = the provider's fixed subfolder (independent per provider).
    """
    if value is None or str(value).strip() == "":
        return PROVIDERS[provider]["local_sub"]
    name = str(value)
    if name != name.strip() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _\-]{0,63}", name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("local folder must be 1-64 chars: letters/digits/space/_/-, "
                    "starting with alnum; no '/' or '..' (e.g. 'Gdrive')"),
        )
    return name

def parse_direction(value: Any) -> str:
    """Allow-list direction (L2)."""
    d = str(value or "bisync")
    if d not in ("upload", "download", "bisync"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"direction must be one of upload/download/bisync, got {d!r}",
        )
    return d


def get_rclone_version() -> Optional[str]:
    """Cached rclone version (computed once at startup)."""
    global _RCLONE_VERSION_CACHE
    if _RCLONE_VERSION_CACHE is None:
        _RCLONE_VERSION_CACHE = rclone_version()
    return _RCLONE_VERSION_CACHE


def sanitize_rclone_output(text: str, max_lines: int = 10) -> str:
    """Redact token-bearing content from rclone output before surfacing to
    browser (M12). Delegates to rclone_ops._redact — ONE central redaction
    implementation, covering 'token =' lines, raw JSON blobs
    (access_token/refresh_token/expiry) and everything from a '[provider]'
    header onward; returns at most max_lines lines.
    """
    from .rclone_ops import _redact
    return "\n".join(_redact(text.splitlines())[:max_lines])


# --------------------------------------------------------------------------- HTML pages

@app.get("/", response_class=HTMLResponse)
async def settings_page(request: Request):
    settings = load_settings()
    providers_state = scheduler.get_state()
    return templates.TemplateResponse(request, "settings.html", {
        "request": request,
        "providers": PROVIDERS,
        "settings": settings,
        "state": providers_state,
        "rclone_version": get_rclone_version(),
        "healthz_ok": True,
    })


@app.get("/connect", response_class=HTMLResponse)
async def connect_page(request: Request):
    settings = load_settings()
    providers_state = scheduler.get_state()
    return templates.TemplateResponse(request, "connect.html", {
        "request": request,
        "providers": PROVIDERS,
        "settings": settings,
        "state": providers_state,
        "rclone_version": get_rclone_version(),
        "healthz_ok": True,
    })


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    history = scheduler.get_history()
    providers_state = scheduler.get_state()
    return templates.TemplateResponse(request, "status.html", {
        "request": request,
        "providers": PROVIDERS,
        "history": history,
        "state": providers_state,
        "rclone_version": get_rclone_version(),
        "healthz_ok": True,
    })


@app.get("/browse", response_class=HTMLResponse)
async def browse_page(request: Request, provider: str = "", path: str = ""):
    """Browse picker page (rendered via Jinja2, not generated in Python)."""
    validate_provider(provider)
    connected = section_present(provider)
    folders = []
    error = None
    if connected:
        # lsd hits the provider API (1-3s+); run it off the event loop,
        # otherwise every popup navigation freezes ALL pages/tabs.
        rc, dirs, err = await asyncio.to_thread(lsd, provider, path)
        if rc != 0:
            error = err
        else:
            folders = dirs
    return templates.TemplateResponse(request, "browse.html", {
        "request": request,
        "provider": provider,
        "path": path,
        "connected": connected,
        "folders": folders,
        "error": error,
        "rclone_version": get_rclone_version(),
        "healthz_ok": True,
    })


# --------------------------------------------------------------------------- /healthz

@app.get("/healthz")
async def healthz():
    """Liveness + aggregated per-provider state (PLANO §8 shape).

    Returns 503 when:
      - rclone binary is missing/invalid, OR
      - consecutive_failures >= 3 in any provider with enabled=true.
    """
    rclone_ver = get_rclone_version()
    providers_state = scheduler.get_state()
    settings = load_settings()

    if rclone_ver is None:
        return JSONResponse(
            {"ok": False, "error": "rclone binary not found",
             "providers": providers_state},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    for provider, prov_settings in settings.get("providers", {}).items():
        if provider not in PROVIDERS:
            continue
        if prov_settings.get("enabled", False):
            if providers_state.get(provider, {}).get("consecutive_failures", 0) >= 3:
                return JSONResponse(
                    {
                        "ok": False,
                        "rclone": rclone_ver,
                        "providers": providers_state,
                        "error": f"{provider} has 3+ consecutive failures",
                    },
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

    return JSONResponse({
        "ok": True,
        "rclone": rclone_ver,
        "providers": providers_state,
    })


# --------------------------------------------------------------------------- API

@app.post("/api/settings")
async def api_save_settings(request: Request):
    data = await request.json()
    provider = validate_provider(data.get("provider"))

    enabled = bool(data.get("enabled", False))
    direction = parse_direction(data.get("direction"))
    interval_min = parse_interval(data.get("interval_min", 5))
    remote = normalize_remote(provider, data.get("remote"))

    mirror = bool(data.get("mirror", False))
    confirm_mirror = bool(data.get("confirm_mirror", False))

    # Mirror guard: mirror=true requires confirm_mirror=true.
    if mirror and not confirm_mirror:
        return JSONResponse(
            {"ok": False, "error": "confirm_required",
             "detail": "Ative a confirmação 'Entendo e quero ativar' antes de salvar o modo espelho."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Mirror is not allowed for bisync (bidirectional already; mirror adds risk).
    if mirror and direction == "bisync":
        return JSONResponse(
            {"ok": False, "error": "mirror_not_allowed_for_bisync",
             "detail": "Modo espelho não é permitido em direção Bidirecional."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Mirror + upload to the provider ROOT is rejected outright: the backup-dir
    # would necessarily overlap the destination (whole drive), and a root mirror
    # would make the entire cloud the sync target.
    if mirror and direction == "upload" and remote == f"{provider}:":
        return JSONResponse(
            {"ok": False, "error": "mirror_root_not_allowed",
             "detail": "Modo espelho com upload para a RAIZ do provedor é bloqueado "
                       "(toda a nuvem seria destino e o backup sobreporia o destino). "
                       "Escolha uma subpasta."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    config = {
        "enabled": enabled,
        "direction": direction,
        "interval_min": interval_min,
        "remote": remote,
        "local_sub": parse_local_sub(data.get("local_sub"), provider),
        "mirror": mirror,
    }

    # Reject enabled=true when the provider remote is not authenticated.
    if enabled and not section_present(provider):
        return JSONResponse(
            {"ok": False,
             "error": f"Cannot enable {provider}: remote not authenticated. "
                      "Connect it first (Conectar Nuvem)."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    settings = load_settings()
    if "providers" not in settings:
        settings["providers"] = {}
    settings["providers"][provider] = config
    save_settings_atomic(settings)
    return {"ok": True}


@app.post("/api/preview")
async def api_preview(request: Request):
    """Dry-run preview: builds the EXACT effective command + --dry-run, runs it
    via rclone (120s timeout), returns counts + tail lines. Never mutates."""
    import asyncio
    from datetime import datetime
    data = await request.json()
    provider = validate_provider(data.get("provider"))
    # Fall back to the SAVED settings for any field the caller omits — never
    # silently preview "upload from provider root" (footgun: targets whole drive).
    saved = scheduler.get_settings().get("providers", {}).get(provider, {})
    direction = parse_direction(data.get("direction") or saved.get("direction", "upload"))
    remote_input = data.get("remote")
    if remote_input is None or remote_input == "":
        remote_input = saved.get("remote", "")
    remote = normalize_remote(provider, remote_input)
    mirror = bool(data.get("mirror", saved.get("mirror", False)))
    local_sub = saved.get("local_sub") or PROVIDERS[provider]["local_sub"]
    local_path = str(Path(SYNC_DIR) / local_sub)

    # Mirror validity must match api_save_settings, so the preview never shows a
    # command the real save would reject (and avoids a 500 from preview()).
    if mirror and direction == "bisync":
        return JSONResponse(
            {"ok": False, "error": "mirror_not_allowed_for_bisync"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if mirror and direction == "upload" and remote == f"{provider}:":
        return JSONResponse(
            {"ok": False, "error": "mirror_root_not_allowed"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Backup-dir must NOT overlap the destination (rclone rejects it).
    # upload: destination is <remote> (a cloud subpath); put the backup at the
    # provider ROOT so it is a sibling, never inside <remote>.  If the remote is
    # itself the root we reject mirror (guard above).
    # download: destination is local /sync/<sub>; back up under /data/deleted.
    from .rclone_ops import utc_ts
    backup_dir = None
    if mirror and direction in ("upload", "download"):
        ts = utc_ts()
        if direction == "upload":
            backup_dir = f"{provider}:.gdrv-deleted/{ts}"
        else:
            backup_dir = str(DATA_DIR / "deleted" / provider / ts)

    first_run = False
    if direction == "bisync":
        from .rclone_ops import bisync_first_run, bisync_was_interrupted
        # Must match the scheduler: --resync runs on first-run OR after an
        # interrupted (killed) bisync, else the preview under-reports.
        first_run = bisync_first_run(provider) or bisync_was_interrupted(provider)

    # rclone writes its dry-run INFO lines directly into this log file.
    log_path = None
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
        log_path = str(DATA_DIR / "logs" / f"preview-{provider}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log")
    except Exception:
        pass

    def _run():
        return preview(direction, local_path, remote, provider,
                       mirror=mirror, backup_dir=backup_dir,
                       first_run=first_run,
                       log_file=log_path or "/tmp/preview.log")

    result = await asyncio.to_thread(_run)

    resp = {"ok": result["ok"], "rc": result["rc"],
            "transfers": result["transfers"], "deletions": result["deletions"],
            "lines": result["lines"], "cmd": result["cmd"]}
    return resp


@app.post("/api/use-dedicated")
async def api_use_dedicated(request: Request):
    """Create the dedicated cloud folder and adopt it as the task's remote.

    Advisor-approved conservative rule: only acts when the task's remote is
    still empty/root AND the task is NOT enabled (never retargets a live task,
    never runs silently on reconnect). mkdir is idempotent; if the folder
    already existed we warn (it may contain real data — review before
    enabling bisync/mirror).
    """
    import asyncio
    data = await request.json()
    provider = validate_provider(data.get("provider"))

    settings = load_settings()
    saved = settings.get("providers", {}).get(provider, {})
    remote = (saved.get("remote") or "").strip()
    if remote not in ("", f"{provider}:"):
        return JSONResponse(
            {"ok": False, "error": "remote_already_set",
             "detail": f"remote atual é '{remote}'; a pasta dedicada só é sugerida quando o destino é a raiz."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if saved.get("enabled"):
        return JSONResponse(
            {"ok": False, "error": "task_enabled",
             "detail": "desabilite a tarefa antes de trocar o destino para a pasta dedicada."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not section_present(provider):
        return JSONResponse(
            {"ok": False, "error": "not_connected",
             "detail": "conecte o provedor primeiro."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    existed = await asyncio.to_thread(remote_is_empty, provider, DEDICATED_FOLDER)
    rc, err = await asyncio.to_thread(mkdir_remote, provider, DEDICATED_FOLDER)
    if rc != 0:
        return JSONResponse(
            {"ok": False, "error": "mkdir_failed",
             "detail": err or "rclone mkdir falhou (escopo sem permissão de escrita?)"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    saved_dir = settings.setdefault("providers", {}).setdefault(provider, {})
    saved_dir["remote"] = f"{provider}:{DEDICATED_FOLDER}"
    save_settings_atomic(settings)
    invalidate_section_cache()  # cheap consistency; remote display refresh

    warning = None
    if existed[0] is False:
        warning = (f"A pasta '{DEDICATED_FOLDER}' já existia e CONTEM dados. "
                   "Revise antes de habilitar Bidirecional ou Espelho — podem alterá-la/apagá-la.")
    elif existed[0] is None:
        warning = (f"Não foi possível verificar se '{DEDICATED_FOLDER}' já tinha conteúdo. "
                   "Confira na UI antes de habilitar modos destrutivos.")

    return {"ok": True,
            "remote": f"{provider}:{DEDICATED_FOLDER}",
            "created_new": existed[0] is not False,
            "warning": warning}


@app.get("/api/settings")
async def api_get_settings():
    return load_settings()


@app.post("/api/connect/start")
async def connect_start(request: Request):
    data = await request.json()
    provider = validate_provider(data.get("provider"))

    # Optional client_id/client_secret (bring-your-own OAuth app credentials).
    # If one is given without the other -> 400.  Never log them.
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    has_cid = client_id is not None and str(client_id).strip() != ""
    has_csec = client_secret is not None and str(client_secret).strip() != ""
    if has_cid != has_csec:
        return JSONResponse(
            {"ok": False, "error": "both_required",
             "detail": "client_id e client_secret devem ser informados juntos (Avançado)."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # rclone authorize listens ONLY on 53682 (no --port flag); keep constant.
    port = 53682
    sess = authorize_start(provider, port,
                           client_id=(str(client_id).strip() if has_cid else None),
                           client_secret=(str(client_secret).strip() if has_csec else None))
    # Run the blocking wait in a threadpool so the event loop isn't blocked up to 60s (M11).
    got_url = await asyncio.to_thread(sess.wait_for_url, 60)

    if sess.auth_url:
        return {"auth_url": sess.auth_url, "status": "waiting"}
    return JSONResponse(
        {"error": "Could not get auth URL", "status": "error",
         "stdout": sanitize_rclone_output(sess.full_output())},
        status_code=status.HTTP_502_BAD_GATEWAY,
    )


@app.get("/api/connect/status")
async def connect_status(provider: str):
    """Check OAuth connection status.

    Uses the file-based section_present (cached, no subprocess per poll) as the
    fast-path and for the already-connected case (M6).  When there is an active
    AuthorizeSession, poll it: token captured -> persist via authorize_finish()
    and return authorized (+ remove session); still running -> waiting; terminal
    without token -> error (+ cleanup session).
    """
    validate_provider(provider)
    connected = section_present(provider)
    if connected:
        # success path: cancel any still-running authorize subprocess for this
        # provider, then drop the stale session (M3).
        sess = get_authorize_session(provider)
        if sess is not None and not sess.is_finished():
            sess.cancel()
        authorize_remove(provider)
        return {"status": "authorized", "connected": True, "token_section": provider}

    sess = get_authorize_session(provider)
    if sess is None:
        return {"status": "waiting", "connected": False}

    if sess.is_finished():
        if sess.has_token():
            ok, message, _ = authorize_finish(provider)
            if ok:
                authorize_remove(provider)  # M3: remove after successful persist
                return {"status": "authorized", "connected": True, "token_section": provider}
            # Persistence failed: surface as error and clean up.
            detail = sanitize_rclone_output(sess.last_lines(20))
            authorize_remove(provider)
            return {"status": "error", "connected": False, "detail": message, "stdout": detail}
        # Terminal without token (subprocess exit / error / cancelled).
        detail = sanitize_rclone_output(sess.last_lines(20))
        authorize_remove(provider)
        return {"status": "error", "connected": False,
                "detail": "authorize ended without a token", "stdout": detail}

    return {"status": "waiting", "connected": False}


@app.post("/api/connect/cancel")
async def connect_cancel(request: Request):
    data = await request.json()
    provider = validate_provider(data.get("provider"))
    authorize_cancel(provider)
    return {"ok": True, "message": "Cancelled"}


@app.post("/api/connect/complete")
async def connect_complete(request: Request):
    """Server-side completion: persist captured token to rclone.conf (idempotent)."""
    data = await request.json()
    provider = validate_provider(data.get("provider"))
    ok, message, _ = authorize_finish(provider)
    if not ok:
        return JSONResponse({"ok": False, "error": message}, status_code=400)
    return {"ok": True, "message": message}


@app.post("/api/run-now")
async def run_now(request: Request):
    data = await request.json()
    provider = validate_provider(data.get("provider"))
    scheduler.enqueue_run_now(provider)
    return {"ok": True, "message": f"Run enqueued for {provider}"}


# --------------------------------------------------------------------------- lifecycle

@app.on_event("startup")
async def startup_event():
    ensure_dirs()
    start_callback_proxy()
    scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.stop()
