from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from cloth_store.domain.models import ImageDetails, SourcePhoto
from cloth_store.infrastructure.assets import LocalAssetStorage
from cloth_store.infrastructure.database import Database, SourcePhotoRepository

_FORMAT_DETAILS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


class ImageIngestionError(ValueError):
    """Base error for invalid image imports."""


class UnsupportedImageError(ImageIngestionError):
    pass


class ImageTooLargeError(ImageIngestionError):
    pass


class InvalidImageError(ImageIngestionError):
    pass


@dataclass(frozen=True, slots=True)
class IngestionResult:
    photo: SourcePhoto
    created: bool


class ImageIngestionService:
    def __init__(
        self,
        *,
        asset_storage: LocalAssetStorage,
        database: Database,
        max_upload_bytes: int,
        allowed_image_types: frozenset[str],
    ) -> None:
        self._asset_storage = asset_storage
        self._database = database
        self._max_upload_bytes = max_upload_bytes
        self._allowed_image_types = allowed_image_types

    def ingest(self, content: bytes) -> IngestionResult:
        if not content:
            raise InvalidImageError("The uploaded file is empty.")
        if len(content) > self._max_upload_bytes:
            raise ImageTooLargeError(
                f"The uploaded image exceeds the {self._max_upload_bytes}-byte limit."
            )

        image_details, media_type, extension = self._inspect(content)
        if media_type not in self._allowed_image_types:
            raise UnsupportedImageError(f"Images of type {media_type} are not supported.")

        content_hash = sha256(content).hexdigest()
        asset_key = f"source/{content_hash[:2]}/{content_hash}.{extension}"

        session = self._database.session_factory()
        try:
            repository = SourcePhotoRepository(session)
            existing = repository.find_by_content_hash(content_hash)
            if existing is not None:
                return IngestionResult(photo=existing, created=False)

            photo = SourcePhoto(
                content_hash=content_hash,
                perceptual_hash=image_details.perceptual_hash,
                asset_key=asset_key,
                media_type=media_type,
                width=image_details.width,
                height=image_details.height,
            )

            self._asset_storage.save(asset_key, content)
            try:
                repository.add(photo)
                session.commit()
            except Exception:
                session.rollback()
                self._asset_storage.delete(asset_key)
                raise
        finally:
            session.close()

        return IngestionResult(photo=photo, created=True)

    @staticmethod
    def _inspect(content: bytes) -> tuple[ImageDetails, str, str]:
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()

            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                if image_format not in _FORMAT_DETAILS:
                    raise UnsupportedImageError(
                        f"Images with format {image_format or 'unknown'} are not supported."
                    )

                normalized = ImageOps.exif_transpose(image)
                width, height = normalized.size
                perceptual_hash = _average_hash(normalized)
        except UnsupportedImageError:
            raise
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
            raise InvalidImageError("The uploaded file is not a valid image.") from error

        media_type, extension = _FORMAT_DETAILS[image_format]
        return ImageDetails(width, height, perceptual_hash), media_type, extension


def _average_hash(image: Image.Image) -> str:
    grayscale = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(grayscale.get_flattened_data())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"
