"""Chain integrity + signature verification on PUSH.

We do NOT verify foreign-actor keys end-to-end here yet — that's
federation work to be wired in later. For v0:
  - same-authority actors: verify against actor objects in our store
  - foreign actors: accept if signature parses (TODO: federate)

The hash chain itself is always verified.
"""

from __future__ import annotations

import json
from typing import Any

from phip import (
    Event,
    hash_event,
    public_key_from_jwk,
    verify_event,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phip_server.db import EventORM, ObjectORM

REQUIRED_FIELDS = {"event_id", "phip_id", "type", "timestamp", "actor", "previous_hash", "payload"}


class ChainError(Exception):
    """code is a PhIP spec error code."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _canon_event(signed: Event) -> Event:
    return {k: v for k, v in signed.items() if k != "signature"}


async def _resolve_actor_jwk(
    session: AsyncSession, actor_uri: str
) -> dict[str, Any] | None:
    """Find the latest JWK for `actor_uri` in this server's data.

    Convention: an actor is a PhIP object whose latest event payload
    carries `attributes.phip:keys` (the JWK). The bootstrap pattern
    in §11.2.4 is a self-signed `created` event.
    """
    obj = await session.get(ObjectORM, actor_uri)
    if obj is None:
        return None
    head_row = (
        await session.execute(
            select(EventORM)
            .where(EventORM.phip_id == actor_uri)
            .order_by(EventORM.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if head_row is None:
        return None
    payload = json.loads(head_row.event_json).get("payload", {})
    keys = payload.get("attributes", {}).get("phip:keys")
    if isinstance(keys, dict) and "x" in keys:
        return keys
    return None


async def validate_event(
    session: AsyncSession,
    signed: Event,
    *,
    allow_self_signed_bootstrap: bool = True,
) -> str:
    """Returns the recomputed event_hash. Raises ChainError on any failure."""
    missing = REQUIRED_FIELDS - signed.keys()
    if missing:
        raise ChainError(
            "INVALID_EVENT", f"event missing required fields: {sorted(missing)}"
        )

    sig = signed.get("signature")
    if not isinstance(sig, dict) or "key_id" not in sig or "value" not in sig:
        raise ChainError("INVALID_EVENT", "event has no signature block")

    # Hash chain link.
    obj = await session.get(ObjectORM, signed["phip_id"])
    expected_prev = obj.head_hash if obj is not None else "genesis"
    if signed["previous_hash"] != expected_prev:
        raise ChainError(
            "CHAIN_CONFLICT",
            "previous_hash does not match current head",
            {"expected": expected_prev, "got": signed["previous_hash"]},
        )

    # Resolve key.
    actor_uri: str = signed["actor"]
    sig_key_id: str = sig["key_id"]

    jwk: dict[str, Any] | None = await _resolve_actor_jwk(session, sig_key_id)

    # Bootstrap pattern: a `created` event where actor == phip_id == sig_key_id
    # is self-signed; the JWK is in its own payload.
    if (
        jwk is None
        and allow_self_signed_bootstrap
        and signed["type"] == "created"
        and signed["phip_id"] == actor_uri == sig_key_id
        and signed["previous_hash"] == "genesis"
    ):
        payload = signed.get("payload", {})
        keys = payload.get("attributes", {}).get("phip:keys")
        if isinstance(keys, dict) and "x" in keys:
            jwk = keys

    if jwk is None:
        raise ChainError(
            "KEY_NOT_FOUND",
            f"could not resolve key {sig_key_id!r} for actor {actor_uri!r}",
        )

    public = public_key_from_jwk(jwk)
    if not verify_event(signed, public):
        raise ChainError("INVALID_SIGNATURE", "signature verification failed")

    return hash_event(signed)


async def has_event(session: AsyncSession, event_id: str) -> bool:
    return (
        await session.execute(
            select(EventORM.event_id).where(EventORM.event_id == event_id).limit(1)
        )
    ).scalar_one_or_none() is not None


async def has_event_by_hash(session: AsyncSession, event_hash: str) -> bool:
    return (
        await session.execute(
            select(EventORM.event_hash).where(EventORM.event_hash == event_hash).limit(1)
        )
    ).scalar_one_or_none() is not None
