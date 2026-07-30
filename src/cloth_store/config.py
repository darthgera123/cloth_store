from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CLOTH_STORE_",
        extra="ignore",
    )

    app_name: str = "Cloth Store API"
    environment: str = "development"
    database_url: str = "sqlite:///data/cloth_store.db"
    asset_directory: Path = Path("data/assets")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    allowed_image_types: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})


@lru_cache
def get_settings() -> Settings:
    return Settings()
