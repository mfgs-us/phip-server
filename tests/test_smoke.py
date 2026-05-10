"""End-to-end: bootstrap actor → CREATE component → PUSH measurement → GET → query → blob."""

from __future__ import annotations

import hashlib

import pytest

pytestmark = pytest.mark.asyncio


async def test_meta(client) -> None:
    resp = await client.get("/.well-known/phip/meta")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authority"] == "test.local"
    assert "0.1.0-draft" in body["protocol_versions"]


async def test_create_get_push_roundtrip(client, make_actor, signed_event_for) -> None:
    authority = "test.local"
    kp, key_id, bootstrap = make_actor(authority, "alice")

    # Bootstrap actor object.
    r = await client.post("/.well-known/phip/objects/keys", json=bootstrap)
    assert r.status_code == 200, r.text
    assert r.json()["history_length"] == 1

    # CREATE a component.
    component_uri = f"phip://{authority}/parts/widget-001"
    create_ev = signed_event_for(
        kp=kp,
        key_id=key_id,
        phip_id=component_uri,
        type_="created",
        previous_hash="genesis",
        payload={"object_type": "component", "state": "concept"},
    )
    r = await client.post("/.well-known/phip/objects/parts", json=create_ev)
    assert r.status_code == 200, r.text
    head_after_create = r.json()["head_hash"]

    # GET it back.
    r = await client.get("/.well-known/phip/resolve/parts/widget-001")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "concept"
    assert body["history_length"] == 1
    assert body["head_hash"] == head_after_create

    # PUSH a measurement.
    measure_ev = signed_event_for(
        kp=kp,
        key_id=key_id,
        phip_id=component_uri,
        type_="measurement",
        previous_hash=head_after_create,
        payload={
            "metric": "freq_response",
            "value": 2.5e6,
            "unit": "Hz",
            "as_of": "2026-05-10T20:00:00Z",
        },
    )
    r = await client.post(
        "/.well-known/phip/push/parts/widget-001", json=measure_ev
    )
    assert r.status_code == 200, r.text
    assert r.json()["history_length"] == 2

    # History.
    r = await client.get("/.well-known/phip/history/parts/widget-001")
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 2
    assert events[0]["type"] == "created"
    assert events[1]["type"] == "measurement"


async def test_chain_conflict(client, make_actor, signed_event_for) -> None:
    authority = "test.local"
    kp, key_id, bootstrap = make_actor(authority, "alice")
    await client.post("/.well-known/phip/objects/keys", json=bootstrap)

    component_uri = f"phip://{authority}/parts/widget-002"
    create_ev = signed_event_for(
        kp=kp, key_id=key_id, phip_id=component_uri, type_="created",
        previous_hash="genesis",
        payload={"object_type": "component", "state": "concept"},
    )
    r = await client.post("/.well-known/phip/objects/parts", json=create_ev)
    assert r.status_code == 200

    # Push with a deliberately wrong previous_hash.
    bad_ev = signed_event_for(
        kp=kp, key_id=key_id, phip_id=component_uri, type_="measurement",
        previous_hash="sha256:" + "0" * 64,
        payload={"metric": "x", "as_of": "2026-05-10T20:00:00Z"},
    )
    r = await client.post(
        "/.well-known/phip/push/parts/widget-002", json=bad_ev
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"]["code"] == "CHAIN_CONFLICT"


async def test_invalid_signature(client, make_actor, signed_event_for) -> None:
    authority = "test.local"
    kp, key_id, bootstrap = make_actor(authority, "alice")
    await client.post("/.well-known/phip/objects/keys", json=bootstrap)

    create_ev = signed_event_for(
        kp=kp, key_id=key_id,
        phip_id=f"phip://{authority}/parts/widget-003",
        type_="created", previous_hash="genesis",
        payload={"object_type": "component", "state": "concept"},
    )
    # Tamper with the payload after signing.
    create_ev["payload"]["state"] = "qualified"
    r = await client.post("/.well-known/phip/objects/parts", json=create_ev)
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "INVALID_SIGNATURE"


async def test_query(client, make_actor, signed_event_for) -> None:
    authority = "test.local"
    kp, key_id, bootstrap = make_actor(authority, "alice")
    await client.post("/.well-known/phip/objects/keys", json=bootstrap)

    for i in range(3):
        ev = signed_event_for(
            kp=kp, key_id=key_id,
            phip_id=f"phip://{authority}/parts/widget-{i:03d}",
            type_="created", previous_hash="genesis",
            payload={"object_type": "component", "state": "concept"},
        )
        r = await client.post("/.well-known/phip/objects/parts", json=ev)
        assert r.status_code == 200

    r = await client.post(
        "/.well-known/phip/query/parts",
        json={"object_type": "component"},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 3
    assert all(r["object_type"] == "component" for r in results)


async def test_blob_put_get_head(client) -> None:
    body = b"hello blob world"
    digest = hashlib.sha256(body).hexdigest()

    r = await client.put(
        f"/.well-known/phip/blobs/{digest}",
        content=body,
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sha256"] == digest

    r = await client.get(f"/.well-known/phip/blobs/{digest}")
    assert r.status_code == 200
    assert r.content == body
    # Starlette appends "; charset=utf-8" for text/* content types.
    assert r.headers["content-type"].startswith("text/plain")

    r = await client.head(f"/.well-known/phip/blobs/{digest}")
    assert r.status_code == 200
    assert int(r.headers["content-length"]) == len(body)


async def test_blob_hash_mismatch_rejected(client) -> None:
    body = b"hello"
    wrong_hash = "0" * 64
    r = await client.put(
        f"/.well-known/phip/blobs/{wrong_hash}", content=body
    )
    assert r.status_code == 400


async def test_write_token_required_when_set(tmp_path) -> None:
    """When PHIP_WRITE_TOKEN is set, writes need the bearer; reads don't."""
    import httpx

    from phip_server.app import bootstrap, create_app
    from phip_server.config import Settings
    from phip_server.db import _engine_cache

    _engine_cache.clear()
    settings = Settings(
        authority="test.local",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'db'}",
        blob_dir=tmp_path / "blobs",
        bootstrap_key_file=tmp_path / "key.json",
        write_token="s3cret",
    )
    app = create_app(settings)
    await bootstrap(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # Read is open.
        r = await c.get("/.well-known/phip/meta")
        assert r.status_code == 200
        # Write without token is rejected.
        r = await c.post("/.well-known/phip/objects/parts", json={"type": "created"})
        assert r.status_code == 401
        assert r.json()["detail"]["error"]["code"] == "MISSING_CAPABILITY"
        # With wrong token.
        r = await c.post(
            "/.well-known/phip/objects/parts",
            json={"type": "created"},
            headers={"Authorization": "Bearer nope"},
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"]["code"] == "INVALID_CAPABILITY"
