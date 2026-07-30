from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from cloth_store.app import create_app
from cloth_store.config import Settings


def _png_image() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 48), color=(30, 50, 80)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_health_endpoint(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        asset_directory=tmp_path / "assets",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_import_is_idempotent(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        asset_directory=tmp_path / "assets",
    )
    image = _png_image()

    with TestClient(create_app(settings)) as client:
        first_response = client.post(
            "/api/v1/source-photos",
            files={"file": ("selfie.png", image, "image/png")},
        )
        second_response = client.post(
            "/api/v1/source-photos",
            files={"file": ("selfie.png", image, "image/png")},
        )

    assert first_response.status_code == 201
    assert first_response.json()["created"] is True
    assert first_response.json()["width"] == 32
    assert first_response.json()["height"] == 48
    assert second_response.status_code == 200
    assert second_response.json()["created"] is False
    assert second_response.json()["id"] == first_response.json()["id"]
    assert len(list((tmp_path / "assets").rglob("*.png"))) == 1


def test_import_rejects_non_image_content(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        asset_directory=tmp_path / "assets",
    )

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/source-photos",
            files={"file": ("selfie.png", b"not an image", "image/png")},
        )

    assert response.status_code == 422
