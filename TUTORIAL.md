# phip-server — Tutorial

How to run a PhIP authority on your laptop, on a VPS, or anywhere
with a Docker daemon. By the end you'll have a server accepting
signed events, persisting them, and serving them back to any PhIP
client.

> **Audience:** operators standing up a PhIP authority. For client
> usage, see [phip-cli](https://github.com/mfgs-us/phip-cli) or
> [phip-py](https://github.com/mfgs-us/phip-py).

## 1. Spin it up

The default Docker Compose profile gives you a single-container
server with SQLite + filesystem blobs — fine for a laptop, a homelab
NUC, or a one-author project:

```bash
git clone https://github.com/mfgs-us/phip-server
cd phip-server
PHIP_AUTHORITY=acme.example docker compose up -d
```

Verify it:

```bash
curl -sf http://localhost:8080/healthz
# {"status":"ok","authority":"acme.example"}

curl -sf http://localhost:8080/.well-known/phip/meta | jq .
```

State lives in the Docker volume `phip-data` (mapped to `/data`
inside the container).

## 2. Write a real value to it

The server validates every CREATE/PUSH: required fields, chain
linkage, and signature against the actor's JWK. Push the bootstrap
actor first (using phip-cli for brevity — `phip-py`'s tutorial shows
the raw Python):

```bash
pip install git+https://github.com/mfgs-us/phip-cli

phip init --remote http://localhost:8080 --authority acme.example
phip key register
phip object new component widget-001 --state concept

phip get phip://acme.example/parts/widget-001
```

You should see the object you just created come back from the
server, with `history_length: 1` and a SHA-256 head hash.

## 3. Production-ish: Postgres + a write token

Single-user SQLite is fine for one author. The moment you have two
clients or care about concurrent writes, switch to Postgres:

```bash
PHIP_AUTHORITY=acme.example \
PHIP_WRITE_TOKEN=$(openssl rand -hex 32) \
docker compose --profile pg up -d
```

Two changes from the default profile:

- **Postgres** starts in a separate container with a persistent
  volume; the server is wired to it via `PHIP_DATABASE_URL`.
- **`PHIP_WRITE_TOKEN`** is set, so the server requires
  `Authorization: Bearer <token>` on all writes. Reads stay open.

Hand the token to your clients:

```bash
phip remote add prod http://localhost:8080 --token "$PHIP_WRITE_TOKEN"
phip remote use prod
phip key register
```

## 4. Behind TLS

The container speaks plain HTTP on 8080. For anything
internet-facing, terminate TLS in front of it. Three options that
all work:

**Caddy** (simplest if you own a domain):

```caddy
acme.example {
    reverse_proxy phip-server:8080
}
```

**nginx**:

```nginx
server {
    listen 443 ssl http2;
    server_name acme.example;
    ssl_certificate     /etc/letsencrypt/live/acme.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/acme.example/privkey.pem;
    location / { proxy_pass http://phip-server:8080; }
}
```

**Tailscale Funnel**: zero TLS config, your tailnet identity handles
auth in front of the bearer token. Useful for cross-org pilots
without provisioning DNS + LE.

## 5. S3-compatible blob backend

For large blobs (PDFs, scope captures, photos), filesystem storage
is fine until it isn't. Switch to S3/R2/MinIO with two env vars and
the `s3` extra:

```bash
# In docker-compose.yml or .env:
PHIP_BLOB_BACKEND=s3
PHIP_S3_BUCKET=phip-blobs-acme
PHIP_S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
# AWS credentials picked up from the standard env / IAM.
```

Install the optional dependency at build time by editing the
Dockerfile's `pip install` step to use `pip install .[s3]`.

## 6. Backups

Everything you care about lives in two places:

- `/data/phip.db` (or your Postgres instance) — events, objects, blob
  registry rows
- `/data/blobs/` (or your S3 bucket) — the actual measurement files
- `/data/bootstrap-key.json` — your server's own actor key. If you
  lose this, the server can still serve client data, but it can't
  re-sign anything as itself. **Copy it somewhere safe on first
  start.**

For the default Docker Compose profile:

```bash
# Periodic backup
docker run --rm -v phip-data:/data -v "$PWD":/backup alpine \
    tar czf /backup/phip-data-$(date +%F).tar.gz -C /data .
```

For Postgres:

```bash
docker compose --profile pg exec postgres pg_dump -U phip -d phip > phip-pg-$(date +%F).sql
```

## 7. What the server enforces

On every CREATE / PUSH:

1. **Required fields** — `event_id`, `phip_id`, `type`, `timestamp`,
   `actor`, `previous_hash`, `payload`, plus a `signature` block.
2. **Authority match** — `phip_id`'s authority must equal
   `PHIP_AUTHORITY`. Cross-authority writes get `FOREIGN_NAMESPACE`.
3. **Chain linkage** — `previous_hash` must equal the current head
   hash (or `"genesis"` for CREATE). Anything else gets
   `CHAIN_CONFLICT`.
4. **Signature** — verifies against the actor's resolved JWK.
   Self-signed bootstrap actors (where `phip_id == actor == sig.key_id`
   and `previous_hash == "genesis"`) are a special case that
   bootstraps the chicken-and-egg.
5. **No duplicates** — `event_id` rejected as `DUPLICATE_EVENT` if
   already stored.

Errors come back as `{"error": {"code": "...", "message": "...", "details": {...}}}`
inside the FastAPI `detail` envelope, with appropriate HTTP status
codes (401 for sig failures, 409 for conflicts, 404 for missing).

## 8. What the server doesn't do (yet)

- **Outbound federation** — fetching foreign-authority JWKs to
  verify cross-authority pushes. Same-authority writes are fine;
  cross-authority verification on read is on the client (`phip
  verify` uses local resolver only).
- **Capability tokens (§11.3)** — server accepts a single bearer
  token. The protocol-level scope/object_filter enforcement is
  pending; phip-cli already mints + parses tokens.
- **Bundles** — the server has no `/bundles` import/export endpoint
  yet. Use `phip bundle pack` to export and ship the file separately.
- **mTLS** — terminate elsewhere (Caddy / nginx / Tailscale).

## 9. Operations notes

- `phip-server` is intentionally single-process. For HA, sit two
  instances behind a load balancer pointed at the same Postgres +
  S3 backend. SQLite mode is single-process only.
- The server logs to stdout. `docker compose logs -f` is the right
  view in dev. In production, ship to your log aggregator like any
  other container.
- Migrations: SQLite uses `create_all` on startup (fine for the
  single-author case). Postgres deployments should run Alembic
  before starting the server — there's a `alembic/` directory with
  the initial schema.

## 10. Hooking it into your workflow

The server is designed to be the boring, fungible part of the
stack. Real workflows happen in clients:

- **Bench data** → `phip-cli`'s `log` composite (see [phip-cli's
  tutorial](https://github.com/mfgs-us/phip-cli/blob/main/TUTORIAL.md)).
- **Cross-org publishing** → `phip bundle pack` produces a verifiable
  static file; host on GitHub Pages, send via email, etc. No server
  on the receiver's side required.
- **Python integration** → talk to the server via
  [`phip-py`](https://github.com/mfgs-us/phip-py)'s `Client` /
  `AsyncClient`.

## What's next

- **[The spec](https://github.com/mfgs-us/phip)** — what the
  endpoints are normatively required to do.
- **[phip-cli](https://github.com/mfgs-us/phip-cli)** — the CLI
  that drives this server end-to-end.
- **[phip-py](https://github.com/mfgs-us/phip-py)** — Python
  library that the server uses for protocol primitives.
