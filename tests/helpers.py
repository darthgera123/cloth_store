"""Shared helpers for the capped scenario test suite (not collected by pytest)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from cloth_store.gemini_catalog_request import (
    ALLOWED_CUTOUT_PREFIX,
    ALLOWED_TEMPLATE_PREFIX,
    SMOKE_FIXTURE_ID,
    SMOKE_ROLE,
    SMOKE_TEMPLATE_ID,
    build_request_artifact,
    write_request_artifact,
)


def write_rgb_square(path: Path, *, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (512, 512), color).save(path)


def make_smoke_repo_tree(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    cutout = repo_root / ALLOWED_CUTOUT_PREFIX / SMOKE_FIXTURE_ID / f"catalog_{SMOKE_ROLE}.png"
    template = repo_root / ALLOWED_TEMPLATE_PREFIX / f"{SMOKE_TEMPLATE_ID}.png"
    write_rgb_square(cutout, color=(200, 120, 80))
    write_rgb_square(template, color=(90, 90, 90))
    artifact = build_request_artifact(
        repo_root=repo_root,
        fixture_id=SMOKE_FIXTURE_ID,
        role=SMOKE_ROLE,
        template_id=SMOKE_TEMPLATE_ID,
    )
    artifact_path = repo_root / "bench/catalog_generation/artifacts/smoke.request.json"
    write_request_artifact(artifact, output_path=artifact_path)
    return repo_root


def make_mock_generation_response(*, size: tuple[int, int] = (1024, 1024)) -> SimpleNamespace:
    response_image = Image.new("RGB", size, color=(220, 210, 200))
    buffer = io.BytesIO()
    response_image.save(buffer, format="PNG")
    return SimpleNamespace(
        parts=[
            SimpleNamespace(
                inline_data=SimpleNamespace(data=buffer.getvalue(), mime_type="image/png"),
                as_image=lambda: None,
            )
        ],
        candidates=[],
    )


def fixed_generation_now() -> datetime:
    return datetime(2026, 8, 1, tzinfo=UTC)
