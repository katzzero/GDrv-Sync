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

from .providers import PROVIDERS
from .rclone_ops import (
    version as rclone_version,
    lsd, check_connected, ensure_dirs, section_present, invalidate_section_cache,
    RCLONE_CONF, LOGS_DIR,
    authorize_start, authorize_finish, authorize_cancel, authorize_remove, write_rclone_section,
    _sessions_lock,
)
from .scheduler import scheduler, SETTINGS_PATH

app = FastAPI()
log = logging.getLogger("gd-sync")

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
    """Redact token-bearing content from rclone output before surfacing to browser (M12).

    Drops any line matching 'token = ' and everything from a '[provider]' header
    onward; returns at most max_lines lines.
    """
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*token\s*=", line, re.I):
            continue
        if re.match(r"^\[", line.strip()):
            break
        lines.append(line)
    return "\n".join(lines[:max_lines])


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
        rc, dirs, err = lsd(provider, path)
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

    config = {
        "enabled": enabled,
        "direction": direction,
        "interval_min": interval_min,
        "remote": remote,
        "local_sub": PROVIDERS[provider]["local_sub"],
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


@app.get("/api/settings")
async def api_get_settings():
    return load_settings()


@app.post("/api/connect/start")
async def connect_start(request: Request):
    data = await request.json()
    provider = validate_provider(data.get("provider"))

    try:
        port = int(os.environ.get("OAUTH_CALLBACK_PORT", "53682"))
    except (TypeError, ValueError):
        port = 53682
        log.warning("invalid OAUTH_CALLBACK_PORT env; falling back to 53682")  # H5

    sess = authorize_start(provider, port)
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
        with _sessions_lock:
            sess = _authorize_sessions.get(provider)
        if sess is not None and not sess.is_finished():
            sess.cancel()
        authorize_remove(provider)
        return {"status": "authorized", "connected": True, "token_section": provider}

    with _sessions_lock:
        sess = _authorize_sessions.get(provider)
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
    scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.stop()
