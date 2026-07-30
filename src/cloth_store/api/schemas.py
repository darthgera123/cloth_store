from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from cloth_store.domain.models import SourcePhoto, SourcePhotoStatus


class HealthResponse(BaseModel):
    status: str


class SourcePhotoResponse(BaseModel):
    id: UUID
    status: SourcePhotoStatus
    media_type: str
    width: int
    height: int
    imported_at: datetime
    created: bool

    @classmethod
    def from_domain(cls, photo: SourcePhoto, *, created: bool) -> "SourcePhotoResponse":
        return cls(
            id=photo.id,
            status=photo.status,
            media_type=photo.media_type,
            width=photo.width,
            height=photo.height,
            imported_at=photo.imported_at,
            created=created,
        )
