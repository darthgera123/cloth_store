from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import DateTime, Enum, Integer, String, Uuid, create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from cloth_store.domain.models import SourcePhoto, SourcePhotoStatus


class Base(DeclarativeBase):
    pass


class SourcePhotoRecord(Base):
    __tablename__ = "source_photos"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    perceptual_hash: Mapped[str] = mapped_column(String(16), index=True)
    asset_key: Mapped[str] = mapped_column(String(512), unique=True)
    media_type: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    status: Mapped[SourcePhotoStatus] = mapped_column(Enum(SourcePhotoStatus, native_enum=False))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Database:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self.engine: Engine = create_engine(database_url)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        url = make_url(self._database_url)
        if url.drivername == "sqlite" and url.database not in {None, ":memory:"}:
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()


class SourcePhotoRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_content_hash(self, content_hash: str) -> SourcePhoto | None:
        record = self._session.scalar(
            select(SourcePhotoRecord).where(SourcePhotoRecord.content_hash == content_hash)
        )
        return _to_domain(record) if record is not None else None

    def add(self, photo: SourcePhoto) -> None:
        self._session.add(
            SourcePhotoRecord(
                id=photo.id,
                content_hash=photo.content_hash,
                perceptual_hash=photo.perceptual_hash,
                asset_key=photo.asset_key,
                media_type=photo.media_type,
                width=photo.width,
                height=photo.height,
                status=photo.status,
                imported_at=photo.imported_at,
            )
        )


def _to_domain(record: SourcePhotoRecord) -> SourcePhoto:
    return SourcePhoto(
        id=record.id,
        content_hash=record.content_hash,
        perceptual_hash=record.perceptual_hash,
        asset_key=record.asset_key,
        media_type=record.media_type,
        width=record.width,
        height=record.height,
        status=record.status,
        imported_at=record.imported_at,
    )
