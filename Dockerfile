FROM python:3.12-slim

# ---------------------------------------------------------------------------
# rclone install: pinned v1.75.2, checksum-verified, arch-matched to the build
# host (uname -m).  Works with both the legacy builder and buildx (which sets
# TARGETPLATFORM).  Hashes were computed from the official GitHub release
# downloads (NOT invented):
#   linux/amd64: 349ac8fba6ff65d6247043f1750cdcb518ec5d500ef91463a10d37c0ccdf3702
#   linux/arm64: 7e1e8d69654941b7b7df84ee74c5f7fb09cce7d5496947fb7bf16b55ff427d10
# If the official release hash cannot be re-verified, run `rclone version` as a
# sanity check after install and document the limitation here (never invent a hash).
# ---------------------------------------------------------------------------
ARG RCLONE_VERSION=1.75.2

RUN set -eux; \
    RCLONE_VER="${RCLONE_VERSION}"; \
    case "$(uname -m)" in \
        aarch64|arm64) \
            RCLONE_ARCH=arm64; \
            RCLONE_SHA256="7e1e8d69654941b7b7df84ee74c5f7fb09cce7d5496947fb7bf16b55ff427d10"; \
            ;; \
        x86_64|amd64) \
            RCLONE_ARCH=amd64; \
            RCLONE_SHA256="349ac8fba6ff65d6247043f1750cdcb518ec5d500ef91463a10d37c0ccdf3702"; \
            ;; \
        *) \
            echo "unsupported arch $(uname -m)" >&2; \
            exit 1; \
            ;; \
    esac && \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
        && rm -rf /var/lib/apt/lists/* \
    && curl -fL "https://github.com/rclone/rclone/releases/download/v${RCLONE_VER}/rclone-v${RCLONE_VER}-linux-${RCLONE_ARCH}.zip" -o /tmp/rclone.zip \
    && echo "${RCLONE_SHA256}  /tmp/rclone.zip" | sha256sum -c - \
    && unzip /tmp/rclone.zip -d /tmp/ \
    && cp /tmp/rclone-v${RCLONE_VER}-linux-${RCLONE_ARCH}/rclone /usr/local/bin/ \
    && chmod +x /usr/local/bin/rclone \
    && rm -rf /tmp/rclone* \
    # Sanity check: the installed binary must report a version.  Unset the ARG
    # (auto-exported as ENV) so rclone does not misread RCLONE_VERSION as a flag.
    && env -u RCLONE_VERSION /usr/local/bin/rclone version

# Install Python dependencies (no extra deps beyond fastapi/uvicorn/jinja2).
RUN pip install --no-cache-dir fastapi uvicorn jinja2

WORKDIR /app
COPY app/ /app/app/

# /data and /sync are volumes/bind mounts — do NOT create /sync/<Provider>
# here (a build-time mkdir is pointless: the compose volume mounts over it).
# Directories are created at runtime by the app (ensure_dirs / scheduler).
RUN mkdir -p /data/logs /data/rclone-state && touch /data/.gitkeep

# Run as a non-root user (H3).  uid 1000 so bind-mounted ./data and ./local are
# typically writable by the host user on Linux/macOS (Colima/Docker Desktop pass
# through the host uid).  NOTE: host ./data must allow uid 1000 writes; the app
# will fail fast (ensure_dirs raises) if it cannot create /data subdirectories.
RUN useradd -m -u 1000 -s /bin/sh gdrv-sync && \
    chown -R gdrv-sync:gdrv-sync /data /app && \
    chmod 755 /data
USER gdrv-sync

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
