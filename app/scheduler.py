"""Scheduler daemon thread for sync operations.

Thread-safety:
  * ``self.lock`` guards the shared state dict (``self.state``,
    ``self.run_now_queue``, ``self.settings``).  Readers
    (get_state/get_history/get_settings/enqueue_run_now) never block on the
    rclone subprocess.
  * ``self._exec_lock`` serializes the actual subprocess execution so only
    one rclone command runs at a time, but it is held only around the
    subprocess call (not the whole state mutation).

The long blocking rclone subprocess is executed OUTSIDE ``self.lock`` so
/healthz, /status and the compose healthcheck (5s timeout) never freeze for
the duration of a sync (up to 3600s).
"""

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .rclone_ops import (
    sync, copy, bisync, check_connected, ensure_dirs,
    RCLONE_CONF, LOGS_DIR, SYNC_DIR, RCLONE_STATE_DIR, DATA_DIR,
    bisync_first_run, section_present, invalidate_section_cache, utc_ts,
)
from .providers import PROVIDERS, MAX_LOG_ENTRIES

SETTINGS_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "settings.json"
log = logging.getLogger("gdrv-sync")


class RunRecord:
    """Record of a single sync run."""

    def __init__(self, provider: str, direction: str, mode: str, returncode: int,
                 start: float, end: float):
        self.provider = provider
        self.direction = direction
        self.mode = mode  # "copy" | "sync+backup" | "bisync"
        self.returncode = returncode
        self.start_ts = datetime.fromtimestamp(start).strftime("%H:%M:%S")
        self.duration = round(end - start, 1)
        self.files_up = 0
        self.files_down = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "direction": self.direction,
            "mode": self.mode,
            "status": "ok" if self.returncode == 0 else f"exit {self.returncode}",
            "start": self.start_ts,
            "duration": self.duration,
            "files_up": self.files_up,
            "files_down": self.files_down,
        }


class ProviderState:
    """State for a single provider."""

    def __init__(self):
        self.running = False
        self.last_ok: Optional[bool] = None
        self.consecutive_failures = 0
        self.next_due: float = 0.0
        self.last_runs: deque = deque(maxlen=MAX_LOG_ENTRIES)

    def to_dict(self, connected: bool = False, enabled: bool = False) -> Dict[str, Any]:
        """PLANO §8 shape: includes connected + enabled."""
        return {
            "running": self.running,
            "last_ok": self.last_ok,
            "consecutive_failures": self.consecutive_failures,
            "next_due": self.next_due,
            "connected": connected,
            "enabled": enabled,
        }


class SyncScheduler:
    """Multi-provider sync scheduler (one task per provider, global state lock)."""

    def __init__(self):
        self.lock = threading.Lock()          # guards shared state
        self._exec_lock = threading.Lock()    # serializes the rclone subprocess only
        self.running_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.state: Dict[str, ProviderState] = {}
        self.settings: Dict[str, Any] = {}
        self.settings_mtime: float = 0.0
        self.run_now_queue: deque = deque()
        self._init_state()

    def _init_state(self):
        for provider in PROVIDERS:
            self.state[provider] = ProviderState()

    # ------------------------------------------------------------------ settings

    def _load_settings(self) -> Dict[str, Any]:
        if not SETTINGS_PATH.exists():
            return self._defaults()
        try:
            with open(SETTINGS_PATH) as f:
                return json.load(f)
        except Exception:
            return self._defaults()

    @staticmethod
    def _defaults() -> Dict[str, Any]:
        return {
            "providers": {
                "gdrive":  {"enabled": False, "direction": "bisync",  "interval_min": 5, "remote": "gdrive:",  "local_sub": "Gdrive"},
                "dropbox": {"enabled": False, "direction": "upload",  "interval_min": 5, "remote": "dropbox:", "local_sub": "Dropbox"},
                "onedrive":{"enabled": False, "direction": "download","interval_min": 10,"remote": "onedrive:", "local_sub": "Onedrive"},
            },
            "extra_flags": [],
        }

    def _reload_settings_if_changed(self) -> bool:
        """Re-read settings.json by mtime (caller must NOT hold self.lock).

        On enable transitions (false->true) reset consecutive_failures and
        next_due so a previously-failing task isn't stuck at 503.
        """
        try:
            mtime = SETTINGS_PATH.stat().st_mtime if SETTINGS_PATH.exists() else 0.0
        except OSError:
            mtime = 0.0
        if mtime != self.settings_mtime:
            settings = self._load_settings()
            with self.lock:
                prev = self.settings.get("providers", {})
                self.settings = settings
                self.settings_mtime = mtime
                for provider in PROVIDERS:
                    ps = settings.get("providers", {}).get(provider, {})
                    was_enabled = bool(prev.get(provider, {}).get("enabled", False))
                    now_enabled = bool(ps.get("enabled", False))
                    if now_enabled and not was_enabled:
                        # Re-enable: clear failure backoff and schedule now.
                        self.state[provider].consecutive_failures = 0
                        self.state[provider].next_due = time.time()
                    elif now_enabled and self.state[provider].next_due == 0.0:
                        self.state[provider].next_due = time.time()
            return True
        return False

    def get_settings(self) -> Dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.settings))  # deep copy

    # ------------------------------------------------------------------ state access (thread-safe, never blocks on subprocess)

    def get_state(self) -> Dict[str, Any]:
        settings = self.get_settings()
        with self.lock:
            return {
                p: self.state[p].to_dict(
                    connected=section_present(p),
                    enabled=bool(settings.get("providers", {}).get(p, {}).get("enabled", False)),
                )
                for p in PROVIDERS
            }

    def get_history(self) -> Dict[str, list]:
        with self.lock:
            return {
                p: [r.to_dict() for r in self.state[p].last_runs]
                for p in PROVIDERS
            }

    # ------------------------------------------------------------------ scheduling

    def _should_run_locked(self, provider: str) -> bool:
        """Caller must hold self.lock."""
        ps = self.settings.get("providers", {}).get(provider, {})
        if not ps.get("enabled", False):
            return False
        # Empty remote ("" or missing) means provider root — allowed (M1).
        remote = ps.get("remote") or f"{provider}:"
        if not check_connected(provider):
            return False
        if self.state[provider].running:
            return False
        if time.time() < self.state[provider].next_due:
            return False
        return True

    def _run_sync(self, provider: str) -> int:
        """Execute one sync for ``provider``.

        Runs the blocking rclone subprocess OUTSIDE self.lock (only inside
        _exec_lock). Returns the returncode; caller updates state.
        Guarantees running=False and a history entry on EVERY path (including
        early mkdir failures) so a provider is never permanently skipped.
        """
        with self.lock:
            ps = self.settings.get("providers", {}).get(provider, {})
            direction = ps.get("direction", "bisync")
            remote = ps.get("remote") or f"{provider}:"
            local_sub = ps.get("local_sub", provider.capitalize())
            local_path = str(Path(SYNC_DIR) / local_sub)
            interval = max(5, int(ps.get("interval_min", 5))) * 60
            mirror = bool(ps.get("mirror", False))

        ts = datetime.now()
        log_file = str(Path(LOGS_DIR) / f"sync-{provider}-{ts.strftime('%Y%m%d-%H%M%S')}.log")
        first_run = bisync_first_run(provider) if direction == "bisync" else False

        # Mirror backup-dir: fresh timestamp per run, computed here so the
        # scheduler (not the UI) owns the runtime value.  upload: cloud-side
        # backup at the provider ROOT (sibling of the destination — using
        # <remote>/... would OVERLAP the destination and rclone rejects it).
        # download: local-side under /data/deleted.  Bisync never uses mirror.
        backup_dir = None
        if mirror and direction in ("upload", "download"):
            if direction == "upload":
                backup_dir = f"{provider}:.gdrv-deleted/{utc_ts()}"
            else:
                backup_dir = str(Path(DATA_DIR) / "deleted" / provider / utc_ts())

        start = time.time()
        returncode = -1
        mode = "copy"  # default non-destructive mode

        # Ensure local dir exists (runtime creation). Failure -> record a failed run.
        try:
            Path(local_path).mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error("scheduler: cannot create local dir %s for %s: %s", local_path, provider, exc)
        else:
            # Ensure provider state dir exists (for bisync marker persistence).
            try:
                (RCLONE_STATE_DIR / provider).mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                log.error("scheduler: cannot create state dir for %s: %s", provider, exc)
            else:
                # --- run the blocking subprocess outside self-lock, inside _exec_lock ---
                with self._exec_lock:
                    with self.lock:
                        self.state[provider].running = True
                    try:
                        if direction == "upload":
                            if mirror:
                                mode = "sync+backup"
                                returncode = sync(local_path, remote, provider, log_file,
                                                  mirror=True, backup_dir=backup_dir)
                            else:
                                returncode = copy(local_path, remote, provider, log_file)
                        elif direction == "download":
                            if mirror:
                                mode = "sync+backup"
                                returncode = sync(remote, local_path, provider, log_file,
                                                  mirror=True, backup_dir=backup_dir)
                            else:
                                returncode = copy(remote, local_path, provider, log_file)
                        else:  # bisync
                            mode = "bisync"
                            returncode = bisync(local_path, remote, provider, log_file,
                                                first_run=first_run)
                    except Exception:
                        returncode = -1
                    with self.lock:
                        self.state[provider].running = False

        end = time.time()
        # Guarantee running=False on every path (incl. early mkdir failures).
        with self.lock:
            self.state[provider].running = False
            record = RunRecord(provider, direction, mode, returncode, start, end)
            self.state[provider].last_runs.appendleft(record)

            if returncode == 0:
                self.state[provider].last_ok = True
                self.state[provider].consecutive_failures = 0
                self.state[provider].next_due = end + interval
            else:
                self.state[provider].last_ok = False
                self.state[provider].consecutive_failures += 1
                # Exponential backoff, capped at 1 hour (M15).
                backoff = interval * (2 ** min(self.state[provider].consecutive_failures, 4))
                self.state[provider].next_due = end + min(backoff, 3600)
        return returncode

    def _tick(self) -> None:
        self._reload_settings_if_changed()
        with self.lock:
            # Run-now (priority) first.
            if self.run_now_queue:
                provider = self.run_now_queue.popleft()
                if provider in PROVIDERS:
                    # Select under lock, run outside lock.
                    provider_to_run = provider
                else:
                    provider_to_run = None
            else:
                provider_to_run = None
                for provider in PROVIDERS:
                    if self._should_run_locked(provider):
                        provider_to_run = provider
                        break
            if provider_to_run is None:
                return
            # Mark running so no other tick picks it while we execute.
            self.state[provider_to_run].running = True

        # Run the subprocess OUTSIDE self.lock (C1). State is updated inside.
        self._run_sync(provider_to_run)

    def _loop(self) -> None:
        try:
            ensure_dirs()
        except RuntimeError as exc:
            log.error("scheduler: ensure_dirs failed: %s", exc)
        self._reload_settings_if_changed()
        while not self.stop_event.is_set():
            self._tick()
            time.sleep(2)

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        # On startup, force --resync for any bisync that was interrupted.
        from .rclone_ops import bisync_was_interrupted
        for provider in PROVIDERS:
            if bisync_was_interrupted(provider):
                log.warning("scheduler: previous bisync for %s was interrupted; forcing --resync", provider)
        if self.running_thread is None or not self.running_thread.is_alive():
            self.stop_event.clear()
            self.running_thread = threading.Thread(target=self._loop, daemon=True)
            self.running_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.running_thread is not None:
            self.running_thread.join(timeout=5)

    def enqueue_run_now(self, provider: str) -> None:
        with self.lock:
            if provider in PROVIDERS:
                self.run_now_queue.append(provider)


# Global scheduler instance
scheduler = SyncScheduler()
