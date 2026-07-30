from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from cloth_store.api.routes import router
from cloth_store.config import Settings, get_settings
from cloth_store.infrastructure.assets import LocalAssetStorage
from cloth_store.infrastructure.database import Database
from cloth_store.services.ingestion import ImageIngestionService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    database = Database(resolved_settings.database_url)
    ingestion_service = ImageIngestionService(
        asset_storage=LocalAssetStorage(resolved_settings.asset_directory),
        database=database,
        max_upload_bytes=resolved_settings.max_upload_bytes,
        allowed_image_types=resolved_settings.allowed_image_types,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        app.state.ingestion_service = ingestion_service
        yield
        database.dispose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()


def run() -> None:
    uvicorn.run("cloth_store.app:app", host="127.0.0.1", port=8000, reload=True)
