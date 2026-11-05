"""TCP forwarder that bridges the published OAuth callback port to the
rclone authorize loopback listener.

``rclone authorize`` binds 127.0.0.1:53682 INSIDE the container, but Docker
port publishing delivers connections to the container's eth0 address — so the
browser's callback (http://127.0.0.1:53682/...) would be refused.  This proxy
listens on 0.0.0.0:<proxy_port> (published as host 53682) and relays each
connection to 127.0.0.1:<target_port> where rclone waits.

Pure stdlib; one thread per connection, bidirectional pipe.
"""

import logging
import os
import socket
import threading
from typing import Optional

log = logging.getLogger("gdrv-sync")

PROXY_PORT = int(os.environ.get("OAUTH_PROXY_PORT", "53683"))
TARGET_PORT = int(os.environ.get("OAUTH_CALLBACK_PORT", "53682"))

_server: Optional[socket.socket] = None
_started = False


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle(conn: socket.socket) -> None:
    try:
        upstream = socket.create_connection(("127.0.0.1", TARGET_PORT), timeout=10)
    except OSError as exc:
        log.warning("callback proxy: rclone not listening on %s (%s)", TARGET_PORT, exc)
        conn.close()
        return
    t1 = threading.Thread(target=_pipe, args=(conn, upstream), daemon=True)
    t2 = threading.Thread(target=_pipe, args=(upstream, conn), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    conn.close()
    upstream.close()


def _accept_loop(server: socket.socket) -> None:
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            break
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


def start_callback_proxy() -> None:
    """Start the forwarder once (idempotent)."""
    global _server, _started
    if _started:
        return
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", PROXY_PORT))
    except OSError as exc:
        log.error("callback proxy cannot bind 0.0.0.0:%s: %s", PROXY_PORT, exc)
        server.close()
        return
    server.listen(16)
    _server = server
    _started = True
    threading.Thread(
        target=_accept_loop, args=(server,), daemon=True, name="oauth-callback-proxy"
    ).start()
    log.info("callback proxy: 0.0.0.0:%s -> 127.0.0.1:%s", PROXY_PORT, TARGET_PORT)
