from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from cloth_store.api.schemas import HealthResponse, SourcePhotoResponse
from cloth_store.services.ingestion import (
    ImageIngestionService,
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedImageError,
)

router = APIRouter()


def get_ingestion_service(request: Request) -> ImageIngestionService:
    return request.app.state.ingestion_service


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/source-photos",
    response_model=SourcePhotoResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["corpus"],
)
async def import_source_photo(
    response: Response,
    file: Annotated[UploadFile, File(description="A private mirror selfie")],
    ingestion_service: Annotated[ImageIngestionService, Depends(get_ingestion_service)],
) -> SourcePhotoResponse:
    try:
        result = ingestion_service.ingest(await file.read())
    except ImageTooLargeError as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error)) from error
    except UnsupportedImageError as error:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(error)) from error
    except InvalidImageError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    finally:
        await file.close()

    if not result.created:
        response.status_code = status.HTTP_200_OK
    return SourcePhotoResponse.from_domain(result.photo, created=result.created)
