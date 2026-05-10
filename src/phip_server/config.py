"""Server configuration via environment variables.

Required:
  PHIP_AUTHORITY               — DNS name this server is authoritative for.

Common:
  PHIP_DATABASE_URL            — SQLAlchemy URL.
                                 Default: sqlite+aiosqlite:///./data/phip.db
  PHIP_BLOB_BACKEND            — "fs" (default) or "s3".
  PHIP_BLOB_DIR                — when fs: directory for blobs.
                                 Default: ./data/blobs
  PHIP_S3_BUCKET, PHIP_S3_ENDPOINT_URL, PHIP_S3_REGION  — when s3.
  PHIP_WRITE_TOKEN             — bearer token required on PUSH and CREATE.
                                 If unset, writes are open (dev only).

Identity:
  PHIP_BOOTSTRAP_KEY_FILE      — JSON file with the server's actor key
                                 (jwk + private_key_b64url). Auto-created
                                 on first start if missing.
                                 Default: ./data/bootstrap-key.json

Behavior:
  PHIP_MAX_BODY_BYTES          — max request body. Default: 1048576 (1 MiB).
  PHIP_HISTORY_PAGE_DEFAULT    — history pagination default. Default: 50.
  PHIP_HISTORY_PAGE_MAX        — history pagination cap. Default: 500.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHIP_", env_file=".env", extra="ignore")

    authority: str = Field(default="localhost")
    database_url: str = Field(default="sqlite+aiosqlite:///./data/phip.db")

    blob_backend: str = Field(default="fs")
    blob_dir: Path = Field(default=Path("./data/blobs"))
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str | None = None

    write_token: str | None = None

    bootstrap_key_file: Path = Field(default=Path("./data/bootstrap-key.json"))

    max_body_bytes: int = 1 * 1024 * 1024
    history_page_default: int = 50
    history_page_max: int = 500


def get_settings() -> Settings:
    return Settings()
