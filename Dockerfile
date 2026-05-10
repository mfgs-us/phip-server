# Build the phip-server image. Multi-stage to keep the runtime small.
FROM python:3.13-slim AS build

WORKDIR /build

# System deps for cryptography wheels (only needed at build time on slim).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/*

# Install phip (path is overridable; default pulls from public GitHub).
ARG PHIP_PY_REF=main
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir "git+https://github.com/mfgs-us/phip-py@${PHIP_PY_REF}"

COPY pyproject.toml README.md /build/
COPY src /build/src
RUN pip install --no-cache-dir .


FROM python:3.13-slim AS runtime

# Non-root for ops hygiene.
RUN groupadd --system app && useradd --system --gid app --create-home app
WORKDIR /app

# Bring over installed packages + entry-point script.
COPY --from=build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=build /usr/local/bin/phip-server /usr/local/bin/phip-server
COPY --from=build /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Pre-create /data with app ownership so the VOLUME inherits it.
# Without this, Docker creates /data as root and the non-root user
# can't write blobs / sqlite.
RUN mkdir -p /data && chown -R app:app /data

USER app
EXPOSE 8080

# Default: SQLite in /data, FS blobs in /data/blobs.
ENV PHIP_DATABASE_URL=sqlite+aiosqlite:////data/phip.db \
    PHIP_BLOB_DIR=/data/blobs \
    PHIP_BOOTSTRAP_KEY_FILE=/data/bootstrap-key.json \
    PHIP_AUTHORITY=localhost

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3); sys.exit(0)" || exit 1

CMD ["phip-server", "--host", "0.0.0.0", "--port", "8080"]
