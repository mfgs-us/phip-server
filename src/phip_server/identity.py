"""Server bootstrap actor key — auto-generated on first start.

The bootstrap key is the actor that signs server-internal events
(e.g., a server-emitted `created` event for the meta object). Client
events are signed by their own keys; the server doesn't need access
to client private keys.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from phip import Keypair, generate_keypair


@dataclass(frozen=True)
class ServerIdentity:
    key_id: str
    keypair: Keypair
    jwk: dict[str, object]


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _years_from_now_iso(years: int) -> str:
    dt = datetime.now(UTC) + timedelta(days=365 * years)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_identity(authority: str, key_path: Path) -> ServerIdentity:
    if key_path.exists():
        data = json.loads(key_path.read_text("utf-8"))
        seed = _b64url_decode(data["private_key_b64url"])
        priv = Ed25519PrivateKey.from_private_bytes(seed)
        kp = Keypair(private=priv, public=priv.public_key())
        return ServerIdentity(
            key_id=data["key_id"], keypair=kp, jwk=data["jwk"]
        )

    kp = generate_keypair()
    key_id = f"phip://{authority}/keys/server"
    jwk: dict[str, object] = {
        **kp.jwk,
        "use": "sig",
        "key_ops": ["verify"],
        "not_before": _now_iso(),
        "not_after": _years_from_now_iso(10),
    }

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(
        json.dumps(
            {
                "key_id": key_id,
                "jwk": jwk,
                "private_key_b64url": _b64url_nopad(kp.private.private_bytes_raw()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return ServerIdentity(key_id=key_id, keypair=kp, jwk=jwk)
