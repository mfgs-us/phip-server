"""SQLAlchemy async engine + session factory + ORM models.

Schema:
  objects        — current state per phip_id (denormalized projection)
  events         — append-only signed event log
  blobs          — content-addressed blob registry (size + media_type)
  attachments    — N:1 attachments per event
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import (
    BigInteger,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from phip_server.config import Settings


class Base(DeclarativeBase):
    pass


class ObjectORM(Base):
    __tablename__ = "objects"

    phip_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    head_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    history_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class EventORM(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phip_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(512), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    event_json: Mapped[str] = mapped_column(Text, nullable=False)
    blob_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (
        UniqueConstraint("phip_id", "seq", name="uq_events_phip_seq"),
        Index("ix_events_phip_seq", "phip_id", "seq"),
        Index("ix_events_actor_ts", "actor", "timestamp"),
    )


class BlobORM(Base):
    __tablename__ = "blobs"

    sha256_hex: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class AttachmentORM(Base):
    __tablename__ = "attachments"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idx: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    blob_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)


# ── Engine / session ─────────────────────────────────────────────────


_engine_cache: dict[str, Any] = {}


def make_engine(url: str) -> Any:
    """SQLite needs check_same_thread=False; Postgres takes pool args."""
    kwargs: dict[str, Any] = {"future": True, "echo": False}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


def get_engine(settings: Settings) -> Any:
    if settings.database_url not in _engine_cache:
        _engine_cache[settings.database_url] = make_engine(settings.database_url)
    return _engine_cache[settings.database_url]


def get_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(settings), expire_on_commit=False, class_=AsyncSession
    )


@asynccontextmanager
async def session_scope(settings: Settings) -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker(settings)
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all(settings: Settings) -> None:
    """Create tables for first-run / SQLite. Postgres should use Alembic."""
    eng = get_engine(settings)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
