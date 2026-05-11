# phip-server

[![CI](https://github.com/mfgs-us/phip-server/actions/workflows/ci.yml/badge.svg)](https://github.com/mfgs-us/phip-server/actions/workflows/ci.yml)
[![spec](https://img.shields.io/badge/spec-v0.1.0--draft-blue)](https://github.com/mfgs-us/phip)

The reference server for the
[Physical Information Protocol](https://github.com/mfgs-us/phip).
Implements the v0.1.0-draft spec endpoints over Postgres (or SQLite)
with filesystem (or S3) blob storage. Reuses
[phip-py](https://github.com/mfgs-us/phip-py) for crypto, JCS
canonicalization, and event/chain primitives so the protocol logic
has one source of truth.

> **Status:** `0.0.1` alpha. Both the spec and this server are
> unstable until `0.1` → `1.0`. Single-process, single-host. Designed
> for self-hosting on a NUC, homelab box, or small VPS.

> **Tutorial:** [TUTORIAL.md](./TUTORIAL.md) covers running locally,
> Postgres + write-token deployment, TLS front-ends, S3 blob backend,
> backups, and what the server enforces on every push.

## Quick start

```bash
docker compose up        # SQLite + filesystem blobs, one container
```

Then:

```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/.well-known/phip/meta
```

For Postgres-backed deployment:

```bash
PHIP_AUTHORITY=acme.example PHIP_WRITE_TOKEN=$(openssl rand -hex 24) \
  docker compose --profile pg up
```

## What it implements

| Endpoint | What it does |
|---|---|
| `GET  /.well-known/phip/meta` | Authority metadata (§12.7) |
| `POST /.well-known/phip/objects/{namespace}` | CREATE a new object via signed `created` event (§12.1) |
| `GET  /.well-known/phip/resolve/{namespace}/{local_id}` | GET current state + history tail (§12.2) |
| `GET  /.well-known/phip/history/{namespace}/{local_id}` | Paginated event history (§12.2.1) |
| `POST /.well-known/phip/push/{namespace}/{local_id}` | Append a signed event to an existing chain (§12.3) |
| `POST /.well-known/phip/query/{namespace}` | Filter objects by type / state / prefix (§12.4) |
| `PUT  /.well-known/phip/blobs/{sha256}` | Upload a content-addressed blob (referenced by `external_ref.content_hash`) |
| `GET  /.well-known/phip/blobs/{sha256}` | Download a blob |
| `HEAD /.well-known/phip/blobs/{sha256}` | Existence + size |
| `GET  /healthz` | Liveness |

On every PUSH/CREATE the server verifies:

1. Required fields (event_id, phip_id, type, timestamp, actor, previous_hash, payload) per spec §11.1
2. `previous_hash` matches current head (`CHAIN_CONFLICT` if not)
3. Signature verifies against the actor's resolved JWK
4. Self-signed bootstrap actors (`§11.2.4`) are accepted as a special case

## Configuration (env vars)

| Var | Default | Notes |
|---|---|---|
| `PHIP_AUTHORITY` | `localhost` | DNS name this server is authoritative for. Required for any real deployment. |
| `PHIP_DATABASE_URL` | `sqlite+aiosqlite:///./data/phip.db` | SQLAlchemy URL. Postgres example: `postgresql+asyncpg://phip:phip@host/phip` |
| `PHIP_BLOB_BACKEND` | `fs` | `fs` or `s3` |
| `PHIP_BLOB_DIR` | `./data/blobs` | When `fs` |
| `PHIP_S3_BUCKET` / `PHIP_S3_ENDPOINT_URL` / `PHIP_S3_REGION` | — | When `s3` (install with `pip install '.[s3]'`) |
| `PHIP_WRITE_TOKEN` | unset | Bearer token required on PUSH / CREATE / blob PUT. **Unset = writes are open.** Set this in production. |
| `PHIP_BOOTSTRAP_KEY_FILE` | `./data/bootstrap-key.json` | Server's own actor key — auto-generated on first start. |
| `PHIP_MAX_BODY_BYTES` | `1048576` (1 MiB) | Request body cap. |

## End-to-end demo against the running server

```bash
# 1. Create a bootstrap actor (self-signed event)
python -c "
import json, uuid
from datetime import datetime, timezone
from phip import generate_keypair, sign_event

kp = generate_keypair()
key_id = 'phip://localhost/keys/alice'
now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
ev = sign_event({
  'event_id': str(uuid.uuid4()),
  'phip_id': key_id, 'type': 'created', 'timestamp': now,
  'actor': key_id, 'previous_hash': 'genesis',
  'payload': {'object_type': 'actor', 'state': 'active',
              'attributes': {'phip:keys': {**kp.jwk,
                'not_before': '2020-01-01T00:00:00Z',
                'not_after':  '2099-01-01T00:00:00Z'}}}
}, kp.private, key_id)
print(json.dumps(ev))
" > actor.json

# 2. POST it
curl -sf -X POST -H 'content-type: application/json' \
     --data @actor.json \
     http://localhost:8080/.well-known/phip/objects/keys

# 3. GET it back
curl -sf http://localhost:8080/.well-known/phip/resolve/keys/alice | jq
```

## Storage layout (filesystem backend)

```
/data/
├── phip.db                  # SQLite (or unused if Postgres)
├── bootstrap-key.json       # server's actor key
└── blobs/sh/<aa>/<hash>     # content-addressed blobs
```

When using Postgres, only `bootstrap-key.json` and `blobs/` live on
disk; everything else is in the database.

## What it does NOT implement yet

- **Outbound federation.** Cannot fetch foreign-authority keys to
  verify cross-authority pushes. Same-authority writes work.
- **Capability tokens (§11.3).** Replaced by a single bearer write
  token. Multi-actor capability scopes are next.
- **Bundles (§4.3.4).** Import/export via tar bundles not yet wired.
- **Subscriptions / streaming.** Polling-only for now.
- **mTLS.** Use a TLS-terminating reverse proxy in front (Caddy, nginx, Traefik).
- **Authority transfer / mirror snapshots.** Single-authority only.

These land as the protocol's needs surface; the chain-validation
core is already in place to support them.

## Development

```bash
git clone https://github.com/mfgs-us/phip-server
cd phip-server
py -m venv .venv
.venv/Scripts/python.exe -m pip install -e ../phip-py    # if local
# or: pip install git+https://github.com/mfgs-us/phip-py@main
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m pytest -q                    # 8 tests
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m mypy src
```

Run a dev server:

```bash
PHIP_AUTHORITY=test.local .venv/Scripts/phip-server.exe --reload
```

## Relation to the spec repo

This server is the reference implementation that
[mfgs-us/phip](https://github.com/mfgs-us/phip) points implementers
at. It supersedes the earlier minimal Node reference that lived in
`phip/reference/`.

## License

Apache 2.0.
