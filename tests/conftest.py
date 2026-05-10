"""Shared pytest fixtures: a fresh sqlite-backed app per test, a
signed-events helper for the chain primitives we need."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from phip import (
    Event,
    generate_keypair,
    sign_event,
)

from phip_server.app import create_app
from phip_server.config import Settings
from phip_server.db import _engine_cache


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    db = tmp_path / "phip.db"
    blobs = tmp_path / "blobs"
    key = tmp_path / "bootstrap-key.json"
    return Settings(
        authority="test.local",
        database_url=f"sqlite+aiosqlite:///{db}",
        blob_dir=blobs,
        bootstrap_key_file=key,
        write_token=None,
    )


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    # Engine cache must be flushed per-test so each gets a fresh sqlite.
    from phip_server.app import bootstrap

    _engine_cache.clear()
    app = create_app(settings)
    await bootstrap(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


# ── Helpers used by tests ────────────────────────────────────────────


@pytest.fixture
def make_actor():
    """Returns a callable that builds (kp, key_id, bootstrap_event)."""

    def _make(authority: str, name: str = "test"):
        kp = generate_keypair()
        key_id = f"phip://{authority}/keys/{name}"
        now = _utc_now_iso()
        unsigned: Event = {
            "event_id": str(uuid.uuid4()),
            "phip_id": key_id,
            "type": "created",
            "timestamp": now,
            "actor": key_id,
            "previous_hash": "genesis",
            "payload": {
                "object_type": "actor",
                "state": "active",
                "attributes": {
                    "phip:keys": {
                        **kp.jwk,
                        "use": "sig",
                        "key_ops": ["verify"],
                        "not_before": "2020-01-01T00:00:00Z",
                        "not_after": "2099-01-01T00:00:00Z",
                    }
                },
            },
        }
        signed = sign_event(unsigned, kp.private, key_id)
        return kp, key_id, signed

    return _make


@pytest.fixture
def signed_event_for():
    """Returns a callable to build an arbitrary signed event."""

    def _make(*, kp, key_id, phip_id, type_, previous_hash, payload):  # noqa: ANN001
        now = _utc_now_iso()
        unsigned: Event = {
            "event_id": str(uuid.uuid4()),
            "phip_id": phip_id,
            "type": type_,
            "timestamp": now,
            "actor": key_id,
            "previous_hash": previous_hash,
            "payload": payload,
        }
        return sign_event(unsigned, kp.private, key_id)

    return _make
