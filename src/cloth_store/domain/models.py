from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class SourcePhotoStatus(StrEnum):
    IMPORTED = "imported"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SourcePhoto:
    content_hash: str
    perceptual_hash: str
    asset_key: str
    media_type: str
    width: int
    height: int
    id: UUID = field(default_factory=uuid4)
    status: SourcePhotoStatus = SourcePhotoStatus.IMPORTED
    imported_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ImageDetails:
    width: int
    height: int
    perceptual_hash: str
