"""Rclone subprocess wrappers.

All data-root paths are derived from the DATA_DIR environment variable
(default ``/data``) so the same code works in-container (``/data``) and
locally (``DATA_DIR=./data``).  The local sync root is ``SYNC_DIR``
(``/sync`` in-container, bind-mounted via docker-compose).
"""

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any

from .providers import PROVIDERS as PROVIDER_META

# ---------------------------------------------------------------------------
# Paths (honor DATA_DIR so the app runs both in-container and locally).
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
RCLONE_CONF = DATA_DIR / "rclone.conf"
RCLONE_STATE_DIR = DATA_DIR / "rclone-state"
LOGS_DIR = DATA_DIR / "logs"
SYNC_DIR = Path(os.environ.get("SYNC_DIR", "/sync"))

PROVIDERS = ["gdrive", "dropbox", "onedrive"]

# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def ensure_dirs() -> None:
    """Ensure runtime directories exist (called at startup, not build time).

    Errors are logged (not swallowed) so a failure to create the provider's
    local sync directory is visible instead of silently causing later
    subprocess failures.
    """
    import logging
    log = logging.getLogger("gdrv-sync")
    errors = []
    # Mirrors may move deleted files into /data/deleted/<provider>/<ts>, so it
    # must exist locally (visible to the user via the host ./data volume).
    for d in (LOGS_DIR, RCLONE_STATE_DIR, DATA_DIR / "deleted"):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            errors.append(str(d))
            log.error("ensure_dirs: cannot create %s: %s", d, exc)
    for provider in PROVIDERS:
        # Honor the configured (possibly custom) local_sub when settings.json
        # exists; fall back to the provider's default subfolder name.
        sub = provider.capitalize()
        try:
            s = json.loads((DATA_DIR / "settings.json").read_text(encoding="utf-8"))
            sub = (s.get("providers", {}).get(provider, {}) or {}).get("local_sub") or sub
        except (OSError, ValueError):
            pass
        for d in (SYNC_DIR / sub, RCLONE_STATE_DIR / provider):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                errors.append(str(d))
                log.error("ensure_dirs: cannot create %s: %s", d, exc)
    if errors:
        raise RuntimeError(f"ensure_dirs: failed to create: {', '.join(errors)}")


def utc_ts() -> str:
    """UTC timestamp for backup-dir names (YYYYmmdd-HHMMSS)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def bisync_marker_path(provider: str) -> Path:
    """Persistent first-run marker for a provider's bisync state."""
    return RCLONE_STATE_DIR / provider / ".bisync_state"


def bisync_running_path(provider: str) -> Path:
    """In-progress bisync marker; forces --resync on next start if present."""
    return RCLONE_STATE_DIR / provider / ".bisync_running"


def bisync_first_run(provider: str) -> bool:
    """True if bisync has never run for this provider (no state marker)."""
    return not bisync_marker_path(provider).exists()


def bisync_mark_run(provider: str) -> None:
    """Persist the bisync first-run marker so it survives restarts."""
    p = bisync_marker_path(provider)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("bisync state initialized\n", encoding="utf-8")


def bisync_mark_running(provider: str) -> None:
    """Mark that a bisync is in progress (forces --resync after a crash)."""
    bisync_mark_running_path = bisync_running_path(provider)
    bisync_mark_running_path.parent.mkdir(parents=True, exist_ok=True)
    bisync_mark_running_path.write_text("bisync in progress\n", encoding="utf-8")


def bisync_clear_running(provider: str) -> None:
    """Clear the in-progress bisync marker after a successful run."""
    try:
        bisync_running_path(provider).unlink(missing_ok=True)
    except FileNotFoundError:
        pass


def bisync_was_interrupted(provider: str) -> bool:
    """True if a previous bisync was interrupted (marker left behind)."""
    return bisync_running_path(provider).exists()


# ---------------------------------------------------------------------------
# Provider connection presence (file-based, no subprocess)
# ---------------------------------------------------------------------------

_section_cache: Dict[str, Tuple[float, bool]] = {}
_SECTION_CACHE_TTL = 10.0


def section_present(provider: str) -> bool:
    """True if ``[provider]`` section exists in rclone.conf with a token= line.

    File-based (no rclone subprocess) with a 10s TTL cache so /healthz and
    connect-status polls don't shell out every time.
    """
    now = time.time()
    cached = _section_cache.get(provider)
    if cached and now - cached[0] < _SECTION_CACHE_TTL:
        return cached[1]
    try:
        text = RCLONE_CONF.read_text(encoding="utf-8") if RCLONE_CONF.exists() else ""
    except OSError:
        text = ""
    present = _has_provider_section(text, provider)
    _section_cache[provider] = (now, present)
    return present


def _has_provider_section(text: str, provider: str) -> bool:
    """Parse INI sections properly and check for [provider] with token=."""
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^\[([^\]]+)\]$", stripped)
        if m:
            current = m.group(1)
            continue
        if current == provider and re.match(r"^\s*token\s*=", stripped, re.I):
            return True
    return False


def invalidate_section_cache(provider: Optional[str] = None) -> None:
    """Drop the section cache (call after writing rclone.conf)."""
    with _conf_lock:
        if provider is None:
            _section_cache.clear()
        else:
            _section_cache.pop(provider, None)


# ---------------------------------------------------------------------------
# Plain (fire-and-forget / blocking) rclone commands
# ---------------------------------------------------------------------------

_conf_lock = threading.Lock()  # guards rclone.conf read-modify-write


def _base_args() -> List[str]:
    return ["--config", str(RCLONE_CONF)]


def _redact(lines: List[str]) -> List[str]:
    """Drop token-bearing lines and everything from a [provider] header onward.

    Covers both INI-style ``token =`` lines and the raw JSON blob printed by
    ``rclone authorize`` between the Paste/End-paste banners (access_token /
    refresh_token keys).  Also drops ``client_secret =`` lines so the secret
    never leaks in error outputs / API responses / logs.
    """
    out: List[str] = []
    for line in lines:
        if re.match(r"^\s*token\s*=", line, re.I):
            continue
        if re.match(r"^\s*client_secret\s*=", line, re.I):
            continue
        if re.search(r"access_token|refresh_token|\"expiry\"", line, re.I):
            continue
        if re.match(r"^\[", line.strip()):
            break
        out.append(line)
    return out


def rclone_cmd(args: list, timeout: int = 300) -> Tuple[int, str, str]:
    """Run a rclone command (blocking) and return (rc, stdout, stderr).

    On timeout the returned stderr names the command so operators can tell
    which rclone invocation expired.
    """
    cmd = ["rclone"] + args + _base_args()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout: rclone {' '.join(args)} exceeded {timeout}s"
    except FileNotFoundError:
        return -1, "", "rclone binary not found"
    except Exception as e:
        return -1, "", str(e)


_AUTH_URL_RE = re.compile(r"https?://[^\s]+")


def _extract_auth_url(stdout: str) -> Optional[str]:
    """Find the auth URL, scanning both per-line and the joined buffer.

    rclone prints at least two URLs: the bare redirect base
    ('"http://127.0.0.1:53682/"' in a NOTICE) and the real auth link
    ('http://127.0.0.1:53682/auth?state=...'). Prefer the one carrying the
    state parameter (or an /auth path); strip trailing quote/punctuation.
    """
    candidates: List[str] = []
    for text in stdout.splitlines() + [stdout.replace("\n", "")]:
        for m in _AUTH_URL_RE.finditer(text):
            url = m.group(0).rstrip('"\',;<>')
            if url not in candidates:
                candidates.append(url)
    if not candidates:
        return None
    for cand in candidates:
        if "state=" in cand or "/auth" in cand:
            return cand
    return candidates[0]


def version() -> Optional[str]:
    """Return the rclone version string (e.g. ``v1.75.2``) or ``None``."""
    returncode, stdout, _ = rclone_cmd(["version"])
    if returncode == 0:
        for line in stdout.strip().splitlines():
            if line.startswith("rclone "):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
    return None


def rclone_binary_ok() -> bool:
    """True if the rclone binary exists and reports a version."""
    return version() is not None


def lsd(provider: str, path: str = "") -> Tuple[int, list, str]:
    """List directories under ``<provider>:<path>``. Returns (rc, dirs, err).

    Uses ``rclone lsjson --dirs-only`` (machine-readable, stable across
    versions) instead of parsing the column-aligned ``lsd`` output, which
    corrupts folder names containing spaces.
    """
    remote = f"{provider}:"
    if path:
        remote = f"{provider}:{path}"
    returncode, stdout, stderr = rclone_cmd(["lsjson", remote, "--dirs-only"], timeout=60)
    if returncode != 0:
        return returncode, [], stderr
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        return -1, [], f"failed to parse lsjson output: {exc}"
    dirs = [e.get("Path") or e.get("Name") for e in data if e.get("IsDir")]
    return 0, dirs, ""


def mkdir_remote(provider: str, folder: str) -> Tuple[int, str]:
    """Create a cloud folder (idempotent — rc=0 if it already exists)."""
    returncode, _, stderr = rclone_cmd(["mkdir", f"{provider}:{folder}"], timeout=60)
    return returncode, stderr


def remote_is_empty(provider: str, folder: str) -> Tuple[Optional[bool], str]:
    """Best-effort emptiness check for the dedicated-folder adoption warning.

    Counts FILES AND SUBFOLDERS (lsd alone would miss files and falsely
    report a folder full of files as "empty").
    Returns (is_empty, err):
      True  -> folder exists and is empty
      False -> folder exists and HAS content (adoption warning)
      None  -> folder does not exist yet ("missing" in err) or check failed.
    """
    returncode, stdout, stderr = rclone_cmd(["lsjson", f"{provider}:{folder}"], timeout=60)
    if returncode != 0:
        low = (stderr or "").lower()
        if "directory not found" in low or "doesn't exist" in low or "not found" in low:
            return None, "missing"
        return None, stderr
    try:
        return len(json.loads(stdout)) == 0, ""
    except ValueError as exc:
        return None, str(exc)


def check_connected(provider: str) -> bool:
    """True if ``rclone lsd <provider>:`` succeeds (remote authenticated)."""
    returncode, _, _ = rclone_cmd(["lsd", f"{provider}:"])
    return returncode == 0


def sync(local_path: str, remote: str, provider: str, log_file: str,
         mirror: bool = False, backup_dir: Optional[str] = None) -> int:
    """Run one-way ``rclone sync``. Returns returncode.

    When ``mirror`` is True, adds ``--backup-dir`` so destination-only files
    are *moved* into backup-dir instead of hard-deleted. ``backup_dir`` must be
    on the destination side (cloud for upload, local for download).

    SAFETY GUARD: mirror without backup_dir would be a HARD DELETE on the
    destination — refused here even if a caller (or hand-edited settings.json)
    requests it. This is the last line of defense against destructive syncs.
    """
    if mirror and not backup_dir:
        raise ValueError("refusing destructive sync without backup-dir (mirror mode requires --backup-dir)")
    cmd = [
        "sync", local_path, remote,
        "-v",  # per-file operation lines in the log (audit + counts)
        "--config", str(RCLONE_CONF),
        "--log-file", log_file,
        "--timeout", "55m",
        "--retries", "3",
    ]
    if mirror and backup_dir:
        cmd += ["--backup-dir", backup_dir]
    returncode, _, _ = rclone_cmd(cmd, timeout=3600)
    return returncode


def copy(source: str, dest: str, provider: str, log_file: str) -> int:
    """Run ``rclone copy`` (non-destructive: never deletes). Returns returncode.

    The default mode for both upload and download directions.  No ``--backup-dir``
    because copy never removes anything from the destination.
    """
    cmd = [
        "copy", source, dest,
        "-v",  # per-file operation lines in the log (audit + counts)
        "--config", str(RCLONE_CONF),
        "--log-file", log_file,
        "--timeout", "55m",
        "--retries", "3",
    ]
    returncode, _, _ = rclone_cmd(cmd, timeout=3600)
    return returncode


def bisync(local_path: str, remote: str, provider: str, log_file: str,
           first_run: bool = False, mirror: bool = False,
           backup_dir: Optional[str] = None,
           conflict_resolve: str = "none") -> int:
    """Run ``rclone bisync``. First run adds ``--resync``. Returns returncode.

    ``mirror`` is not a valid bisync mode — the caller/API must reject it
    before reaching here. ``conflict_resolve`` defaults to ``none`` (conflict
    = abort, no winner chosen).
    """
    if mirror:
        raise ValueError("bisync does not support mirror mode")
    bisync_mark_running(provider)
    try:
        cmd = [
            "bisync", local_path, remote,
            "-v",  # per-file operation lines in the log (audit + counts)
            "--config", str(RCLONE_CONF),
            "--log-file", log_file,
            "--timeout", "55m",
            "--retries", "3",
            "--conflict-resolve", conflict_resolve,
        ]
        if first_run or bisync_was_interrupted(provider):
            cmd.append("--resync")
        returncode, _, _ = rclone_cmd(cmd, timeout=3600)
        if returncode == 0:
            bisync_mark_run(provider)
        return returncode
    finally:
        bisync_clear_running(provider)


# ---------------------------------------------------------------------------
# Dry-run preview (read-only: never mutates anything)
# ---------------------------------------------------------------------------

def count_transfers(log_file: str, direction: str) -> Tuple[int, int]:
    """Parse a real (non-dry-run) rclone log for transferred files.

    Returns (up, down): upload direction -> all copies are 'up'; download ->
    all 'down'; bisync -> (None, None) because per-file direction markers in
    bisync logs are not reliably parseable — the UI shows '—' instead of a
    fake 0/0.
    """
    try:
        content = Path(log_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return (0, 0) if direction != "bisync" else (None, None)
    n = sum(1 for line in content.splitlines() if "Copied (" in line)
    if direction == "upload":
        return n, 0
    if direction == "download":
        return 0, n
    return None, None


def preview(direction: str, local_path: str, remote: str, provider: str,
            mirror: bool = False, backup_dir: Optional[str] = None,
            first_run: bool = False, conflict_resolve: str = "none",
            timeout: int = 120, log_file: str = "/tmp/preview.log") -> Dict[str, Any]:
    """Build the exact effective command (incl mirror/backup-dir/bisync first-run
    state) plus ``--dry-run`` and run it via rclone. Never mutates anything.

    Returns a dict with keys:
      ok (bool), rc (int), transfers (int), deletions (int),
      lines (list[str] tail up to 80 sanitized), cmd (list[str]).
    """
    if direction == "bisync":
        if mirror:
            raise ValueError("bisync does not support mirror mode")
        cmd = [
            "bisync", local_path, remote,
            "--log-file", log_file,
            "--timeout", "55m",
            "--retries", "3",
            "--conflict-resolve", conflict_resolve,
            "--dry-run",
        ]
        if first_run:
            cmd.append("--resync")
        base_desc = "bisync"
    elif direction == "upload":
        # Mirror mode uses rclone sync (+ --backup-dir) so would-be deletions are
        # moved to the backup-dir instead of hard-deleted. Non-mirror uses copy.
        if mirror:
            cmd = [
                "sync", local_path, remote,
                "--log-file", log_file,
                "--timeout", "55m",
                "--retries", "3",
                "--dry-run",
            ]
            if backup_dir:
                cmd += ["--backup-dir", backup_dir]
        else:
            cmd = [
                "copy", local_path, remote,
                "--log-file", log_file,
                "--timeout", "55m",
                "--retries", "3",
                "--dry-run",
            ]
        base_desc = "sync" if mirror else "copy"
    elif direction == "download":
        if mirror:
            cmd = [
                "sync", remote, local_path,
                "--log-file", log_file,
                "--timeout", "55m",
                "--retries", "3",
                "--dry-run",
            ]
            if backup_dir:
                cmd += ["--backup-dir", backup_dir]
        else:
            cmd = [
                "copy", remote, local_path,
                "--log-file", log_file,
                "--timeout", "55m",
                "--retries", "3",
                "--dry-run",
            ]
        base_desc = "sync" if mirror else "copy"
    else:
        raise ValueError(f"unknown direction: {direction!r}")

    # rclone_cmd() appends _base_args() (--config ...). Build the full effective
    # command for the report and pass the rclone subcommand portion to rclone_cmd.
    full_cmd = ["rclone"] + cmd + _base_args()
    returncode, stdout, stderr = rclone_cmd(cmd, timeout=timeout)

    # With --log-file, per-operation INFO lines land in the LOG FILE, not
    # stdout.  Read the log back; fall back to stdout+stderr if missing.
    log_lines: List[str] = []
    try:
        log_lines = Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        pass
    if not log_lines:
        log_lines = ((stdout or "") + "\n" + (stderr or "")).splitlines()

    lines = _redact(log_lines)

    transfers = 0
    deletions = 0
    for line in lines:
        low = line.lower()
        # rclone 1.75 dry-run NOTICE lines:
        #   "name: Skipped copy as --dry-run is set"      (transfer planned)
        #   "name: Skipped delete as --dry-run is set"    (deletion planned)
        # Older/other formats kept as fallbacks: "Copied (", "Deleted:".
        if "skipped copy" in low or "copied (" in low:
            transfers += 1
        elif "skipped delete" in low or "deleted (" in low or "deleted:" in low:
            deletions += 1

    tail = lines[-80:]

    return {
        "ok": returncode == 0,
        "rc": returncode,
        "transfers": transfers,
        "deletions": deletions,
        "lines": tail,
        "cmd": full_cmd,
    }


# ---------------------------------------------------------------------------
# OAuth authorize (streaming, deadlock-safe, cancellable)
# ---------------------------------------------------------------------------

class AuthorizeSession:
    """Manage a single ``rclone authorize <provider>`` subprocess.

    Reads stdout line-by-line in a background thread (no stream deadlock),
    captures the auth URL to redirect the user's browser, then captures the
    token blob printed after the OAuth callback and persists it to
    ``/data/rclone.conf``.
    """

    def __init__(self, provider: str, port: int = 53682,
                 client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.provider = provider
        self.port = port
        # client_id/client_secret are passed positionally to `rclone authorize`
        # only when BOTH are provided (non-empty).  Stored here so the write path
        # can append client_id = / client_secret = lines to the persisted section.
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        if client_id is not None or client_secret is not None:
            # Require both together; validate non-empty and strip whitespace.
            cid = (client_id or "").strip()
            csec = (client_secret or "").strip()
            if not cid or not csec:
                raise ValueError("client_id and client_secret must be provided together (both non-empty)")
            self.client_id = cid
            self.client_secret = csec
        self.proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._lines: List[str] = []
        self.auth_url: Optional[str] = None
        self.token_section: Optional[str] = None
        self.status = "starting"  # starting | url_ready | done | error | cancelled
        self.error: Optional[str] = None
        self._url_found = threading.Event()
        self._finished = False  # guard: authorize_finish persists at most once

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Launch ``rclone authorize`` and begin streaming stdout.

        ``rclone authorize`` takes a BACKEND name (drive/dropbox/onedrive),
        not a remote name — map via providers.PROVIDERS[*].rclone_type.
        There is no ``--port`` flag: it always listens on 127.0.0.1:53682
        (the callback port published in compose).
        """
        backend = PROVIDER_META[self.provider]["rclone_type"]
        cmd = [
            "rclone", "authorize", backend,
            "--auth-no-open-browser",
            "--config", str(RCLONE_CONF),
        ]
        # client_id + client_secret are POSITIONAL args to `rclone authorize`
        # (backend [client_id client_secret]); pass only when BOTH are set.
        if self.client_id is not None and self.client_secret is not None:
            cmd += [self.client_id, self.client_secret]
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert self.proc.stdout is not None
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        """Read stdout line by line; detect auth URL and token section."""
        assert self.proc is not None and self.proc.stdout is not None
        weak_url: Optional[str] = None
        try:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                with self._lock:
                    self._lines.append(line)
                # rclone prints a bare redirect-base NOTICE first
                # ("... http://127.0.0.1:53682/ ...") and then the real auth
                # link ("...auth?state=..."). Prefer the strong URL; hold the
                # weak one only as a fallback if nothing better ever shows.
                if self.auth_url is None:
                    m = _extract_auth_url(line)
                    if m:
                        if "state=" in m or "/auth" in m:
                            self.auth_url = m
                            with self._lock:
                                self.status = "url_ready"
                            self._url_found.set()
                        elif weak_url is None:
                            weak_url = m
        except Exception as exc:  # pragma: no cover - defensive
            with self._lock:
                self.error = str(exc)
                self.status = "error"
        finally:
            rc = self.proc.wait() if self.proc else -1
            # All lines are now accumulated: capture the token section if present.
            self._capture_token_section()
            if self.auth_url is None and weak_url:
                self.auth_url = weak_url
                self._url_found.set()
            with self._lock:
                if self.status not in ("done", "cancelled"):
                    self.status = "done" if rc == 0 else "error"

    def _capture_token_section(self) -> None:
        """Build the ``[provider]`` config section from accumulated stdout.

        PRIMARY contract (rclone >= 1.55, confirmed against v1.75.2 source,
        fs/config/authorize.go): after a successful exchange rclone prints
        ONLY the raw token JSON between banners::

            Paste the following into your remote machine --->
            {"access_token":"...","refresh_token":"...", ...}
            <---End paste

        Legacy/alternate INI form (``[drive] ... token = {...}``) is also
        accepted as fallback.  In all cases the section header is normalized
        to the provider (remote) name used across the app.
        """
        with self._lock:
            lines = list(self._lines)

        rclone_type = PROVIDER_META[self.provider]["rclone_type"]
        token_json: Optional[str] = None

        # -- primary: banner-delimited JSON blob --
        in_blob = False
        collected: List[str] = []
        for line in lines:
            if not in_blob:
                if line.rstrip().endswith("--->") and "Paste the following" in line:
                    in_blob = True
                continue
            if "<---End paste" in line:
                break
            collected.append(line.strip())
        blob = "".join(collected).strip()
        if blob.startswith("{") and blob.endswith("}"):
            token_json = blob

        # -- fallback: legacy INI section --
        if token_json is None:
            headers = {f"[{self.provider}]", f"[{rclone_type}]"}
            started = False
            ini: List[str] = []
            for line in lines:
                if line.strip() in headers:
                    started = True
                    continue
                if started:
                    if line.strip() == "" or line.strip().startswith("["):
                        break
                    ini.append(line)
            for ln in ini:
                if ln.strip().startswith("token"):
                    token_json = ln.split("=", 1)[1].strip()
                    break
            else:
                token_json = None

        if token_json:
            section = (
                f"[{self.provider}]\n"
                f"type = {rclone_type}\n"
                f"token = {token_json}\n"
            )
            # When custom OAuth credentials were provided, persist them inside
            # the provider section (after the token line) — this is how rclone
            # stores them.  They stay ONLY in rclone.conf (the volume).
            if self.client_id is not None and self.client_secret is not None:
                section += f"client_id = {self.client_id}\n"
                section += f"client_secret = {self.client_secret}\n"
            self.token_section = section
            with self._lock:
                self.status = "done"

    # -- query / control --------------------------------------------------

    def pending_url(self) -> Optional[str]:
        with self._lock:
            return self.auth_url

    def is_url_ready(self) -> bool:
        with self._lock:
            return self.status == "url_ready" or self.auth_url is not None

    def wait_for_url(self, timeout: float = 30.0) -> bool:
        return self._url_found.wait(timeout)

    def get_token_section(self) -> Optional[str]:
        with self._lock:
            return self.token_section

    def get_status(self) -> str:
        with self._lock:
            return self.status

    def has_token(self) -> bool:
        """True if a token blob was captured (ready to be persisted)."""
        with self._lock:
            return self.token_section is not None

    def is_finished(self) -> bool:
        """True if the authorize subprocess has exited (done/error/cancelled)."""
        with self._lock:
            return self.status in ("done", "error", "cancelled")

    def last_lines(self, n: int = 20) -> str:
        """Return the last ``n`` stdout lines, token-redacted (for error surfacing)."""
        with self._lock:
            lines = list(self._lines[-n:])
        return "\n".join(_redact(lines))

    def full_output(self) -> str:
        """Return all captured stdout lines, token-redacted."""
        with self._lock:
            lines = list(self._lines)
        return "\n".join(_redact(lines))

    def cancel(self) -> None:
        """Terminate the authorize subprocess (robust cleanup on cancel)."""
        with self._lock:
            if self.status in ("done", "cancelled", "error"):
                return
            self.status = "cancelled"
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


# Module-level registry of in-flight authorize sessions (one per provider).
_authorize_sessions: Dict[str, AuthorizeSession] = {}
_sessions_lock = threading.Lock()


def authorize_start(provider: str, port: int = 53682,
                    client_id: Optional[str] = None, client_secret: Optional[str] = None) -> AuthorizeSession:
    """Start (or reuse) an authorize session for ``provider``.

    If an existing session is finished (terminal), replace it with a fresh
    one so re-Connect always re-initiates the flow.  Threads optional
    client_id/client_secret through to the session (both required together;
    passed as positional args to `rclone authorize`).
    """
    with _sessions_lock:
        sess = _authorize_sessions.get(provider)
        if sess is not None and sess.is_finished():
            _authorize_sessions.pop(provider, None)
            sess = None
        if sess is None:
            sess = AuthorizeSession(provider, port, client_id=client_id, client_secret=client_secret)
            _authorize_sessions[provider] = sess
        if sess.proc is None:
            sess.start()
        return sess


def authorize_finish(provider: str) -> Tuple[bool, str, str]:
    """Persist a captured token blob to rclone.conf (idempotent: runs once).

    Returns (ok, message, token_section_or_error).
    Sets the _finished guard only AFTER a successful write, so a failed
    write leaves the session retryable.
    """
    with _sessions_lock:
        sess = _authorize_sessions.get(provider)
    if sess is None:
        return False, "no authorize session in progress", ""

    # Read status/token under the lock without calling the public getters
    # (those re-acquire the non-reentrant lock -> deadlock).
    with sess._lock:
        if sess._finished:
            return True, f"token for {provider} already written to {RCLONE_CONF}", sess.token_section or ""
        status = sess.status
        token_section = sess.token_section
        if status != "done" or not token_section:
            return False, "authorize not yet complete (waiting for OAuth callback)", ""

    ok = write_rclone_section(provider, token_section)
    if ok:
        with sess._lock:
            sess._finished = True
        invalidate_section_cache(provider)
        return True, f"token for {provider} written to {RCLONE_CONF}", token_section
    # Write failed: do NOT set _finished, keep the session retryable.
    return False, "failed to write rclone.conf", ""


def authorize_cancel(provider: str) -> None:
    with _sessions_lock:
        sess = _authorize_sessions.get(provider)
    if sess is not None:
        sess.cancel()


def authorize_remove(provider: str) -> None:
    """Drop an in-flight session from the registry (after terminal state)."""
    with _sessions_lock:
        _authorize_sessions.pop(provider, None)


def get_authorize_session(provider: str) -> Optional[AuthorizeSession]:
    """Return the active AuthorizeSession for ``provider`` (or None)."""
    with _sessions_lock:
        return _authorize_sessions.get(provider)


def write_rclone_section(provider: str, section_text: str) -> bool:
    """Write/replace the ``[provider]`` section in rclone.conf atomically.

    The whole read-modify-write is guarded by a dedicated module-level lock
    so concurrent provider writes cannot corrupt each other's RMW cycle.
    """
    with _conf_lock:
        try:
            RCLONE_CONF.parent.mkdir(parents=True, exist_ok=True)
            existing = ""
            if RCLONE_CONF.exists():
                existing = RCLONE_CONF.read_text(encoding="utf-8")
            cleaned = _remove_section(existing, provider)
            merged = cleaned.rstrip() + "\n\n" + section_text.strip() + "\n"
            # Atomic write: tmp + rename.
            tmp_path = RCLONE_CONF.with_suffix(".conf.tmp")
            tmp_path.write_text(merged, encoding="utf-8")
            os.replace(tmp_path, RCLONE_CONF)
            return True
        except Exception:
            return False


def _remove_section(text: str, provider: str) -> str:
    """Remove a whole ``[provider]`` section (header + body) from INI text.

    Parses sections properly (split on lines matching ^[...]$) so the body
    is not orphaned on re-auth.
    """
    lines = text.splitlines()
    out: List[str] = []
    skip = False
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^\[([^\]]+)\]$", stripped)
        if m:
            skip = (m.group(1) == provider)
            if not skip:
                out.append(line)
            continue
        if not skip:
            out.append(line)
    return "\n".join(out).rstrip() + "\n"


# Backwards-compatible name used by older code.
