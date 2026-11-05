"""Rclone subprocess wrappers.

All data-root paths are derived from the DATA_DIR environment variable
(default ``/data``) so the same code works in-container (``/data``) and
locally (``DATA_DIR=./data``).  The local sync root is ``SYNC_DIR``
(``/sync`` in-container, bind-mounted via docker-compose).
"""

import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, List

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
    log = logging.getLogger("gd-sync")
    errors = []
    for d in (LOGS_DIR, RCLONE_STATE_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            errors.append(str(d))
            log.error("ensure_dirs: cannot create %s: %s", d, exc)
    for provider in PROVIDERS:
        for d in (SYNC_DIR / provider.capitalize(), RCLONE_STATE_DIR / provider):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                errors.append(str(d))
                log.error("ensure_dirs: cannot create %s: %s", d, exc)
    if errors:
        raise RuntimeError(f"ensure_dirs: failed to create: {', '.join(errors)}")


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
    """Drop token-bearing lines and everything from a [provider] header onward."""
    out: List[str] = []
    for line in lines:
        if re.match(r"^\s*token\s*=", line, re.I):
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
    """Find an auth URL, scanning both per-line and the joined buffer."""
    for line in stdout.splitlines():
        m = _AUTH_URL_RE.search(line)
        if m:
            return m.group(0)
    m = _AUTH_URL_RE.search(stdout.replace("\n", ""))
    return m.group(0) if m else None


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

    Filters rclone's trailing "Total: N dirs" summary line out of results.
    """
    remote = f"{provider}:"
    if path:
        remote = f"{provider}:{path}"
    returncode, stdout, stderr = rclone_cmd(["lsd", remote])
    if returncode != 0:
        return returncode, [], stderr
    dirs: List[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        if line.strip().startswith("Total:"):
            continue
        # rclone lsd output is tab-separated; the last field is the name.
        parts = line.split("\t")
        if parts:
            dirs.append(parts[-1])
    return 0, dirs, ""


def check_connected(provider: str) -> bool:
    """True if ``rclone lsd <provider>:`` succeeds (remote authenticated)."""
    returncode, _, _ = rclone_cmd(["lsd", f"{provider}:"])
    return returncode == 0


def sync(local_path: str, remote: str, provider: str, log_file: str) -> int:
    """Run one-way ``rclone sync``. Returns returncode."""
    cmd = [
        "sync", local_path, remote,
        "--config", str(RCLONE_CONF),
        "--log-file", log_file,
        "--timeout", "55m",
        "--retries", "3",
    ]
    returncode, _, _ = rclone_cmd(cmd, timeout=3600)
    return returncode


def bisync(local_path: str, remote: str, provider: str, log_file: str,
           first_run: bool = False) -> int:
    """Run ``rclone bisync``. First run adds ``--resync``. Returns returncode."""
    bisync_mark_running(provider)
    try:
        cmd = [
            "bisync", local_path, remote,
            "--config", str(RCLONE_CONF),
            "--log-file", log_file,
            "--timeout", "55m",
            "--retries", "3",
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
# OAuth authorize (streaming, deadlock-safe, cancellable)
# ---------------------------------------------------------------------------

class AuthorizeSession:
    """Manage a single ``rclone authorize <provider>`` subprocess.

    Reads stdout line-by-line in a background thread (no stream deadlock),
    captures the auth URL to redirect the user's browser, then captures the
    token blob printed after the OAuth callback and persists it to
    ``/data/rclone.conf``.
    """

    def __init__(self, provider: str, port: int = 53682):
        self.provider = provider
        self.port = port
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
        """Launch ``rclone authorize`` and begin streaming stdout."""
        cmd = [
            "rclone", "authorize", self.provider, "--port", str(self.port),
            "--config", str(RCLONE_CONF),
        ]
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
        try:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                with self._lock:
                    self._lines.append(line)
                # Auth URL: rclone prints something like
                # "If your browser doesn't open automatically go to the following
                #  link: https://accounts.google.com/..." or a bare https URL.
                if self.auth_url is None:
                    m = _extract_auth_url(line)
                    if m:
                        self.auth_url = m
                        with self._lock:
                            self.status = "url_ready"
                        self._url_found.set()
        except Exception as exc:  # pragma: no cover - defensive
            with self._lock:
                self.error = str(exc)
                self.status = "error"
        finally:
            rc = self.proc.wait() if self.proc else -1
            # All lines are now accumulated: capture the token section if present.
            self._capture_token_section()
            with self._lock:
                if self.status not in ("done", "cancelled"):
                    self.status = "done" if rc == 0 else "error"

    def _capture_token_section(self) -> None:
        """Capture the [provider] config block (token) from accumulated lines."""
        with self._lock:
            lines = list(self._lines)
        started = False
        captured: List[str] = []
        for line in lines:
            if line.strip() == f"[{self.provider}]":
                started = True
                captured.append(line)
                continue
            if started:
                if line.strip() == "" or line.strip().startswith("["):
                    break
                captured.append(line)
        if started and captured:
            self.token_section = "\n".join(captured)
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


def authorize_start(provider: str, port: int = 53682) -> AuthorizeSession:
    """Start (or reuse) an authorize session for ``provider``.

    If an existing session is finished (terminal), replace it with a fresh
    one so re-Connect always re-initiates the flow.
    """
    with _sessions_lock:
        sess = _authorize_sessions.get(provider)
        if sess is not None and sess.is_finished():
            _authorize_sessions.pop(provider, None)
            sess = None
        if sess is None:
            sess = AuthorizeSession(provider, port)
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
def authorize(provider: str, port: int = 53682) -> Tuple[int, str, str]:
    """Blocking authorize (kept for compatibility). Prefer authorize_start."""
    sess = authorize_start(provider, port)
    got_url = sess.wait_for_url(timeout=60)
    output = sess.full_output()
    if sess.get_status() == "done":
        return 0, output, ""
    if got_url and sess.auth_url:
        return 0, output, ""
    return -1, output, "authorize did not complete"
