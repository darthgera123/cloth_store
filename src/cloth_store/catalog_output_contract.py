"""Canonical 1K output contract and validation for catalog generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from cloth_store.catalog_templates import CANVAS_SIZE
from cloth_store.gemini_catalog import GEMINI_API_KEY_ENV
from cloth_store.gemini_catalog_generate import CatalogGenerationError

CANONICAL_COST_1K_USD = 0.067
CANONICAL_IMAGE_SIZE = "1K"

BASE_PRODUCTION_POLICY: dict[str, str | bool] = {
    "api_resolution": CANONICAL_IMAGE_SIZE,
    "local_derivative": "512x512",
    "derivative_method": "LANCZOS",
    "one_call_maximum": True,
    "automatic_retries": False,
}


def production_policy(**extra: Any) -> dict[str, Any]:
    """Return the standard production policy block with optional promotion fields."""
    return {**BASE_PRODUCTION_POLICY, **extra}


@dataclass(frozen=True)
class CanonicalOutputPaths:
    raw_1k_path: Path
    catalog_512_path: Path
    metadata_path: Path


def validate_canonical_outputs(paths: CanonicalOutputPaths | None) -> None:
    if paths is None:
        raise CatalogGenerationError("canonical outputs missing")
    for path in (paths.raw_1k_path, paths.catalog_512_path, paths.metadata_path):
        if not path.is_file():
            raise CatalogGenerationError(f"expected canonical output missing: {path}")
    with Image.open(paths.raw_1k_path) as raw:
        if raw.width != raw.height:
            raise CatalogGenerationError("canonical raw 1K output must be square")
        if raw.width < CANVAS_SIZE:
            raise CatalogGenerationError("canonical raw 1K output smaller than catalog canvas")
    with Image.open(paths.catalog_512_path) as catalog:
        if catalog.size != (CANVAS_SIZE, CANVAS_SIZE):
            raise CatalogGenerationError(
                f"canonical catalog derivative must be {CANVAS_SIZE}x{CANVAS_SIZE}"
            )
        if catalog.mode != "RGB":
            raise CatalogGenerationError("canonical catalog derivative must be RGB")


def estimate_canonical_cost_usd(*, count: int, manifest: dict | None = None) -> float:
    if manifest is not None:
        rate = manifest.get("cost_estimates_usd_per_image_output", {}).get("1K")
        if rate is not None:
            return round(count * float(rate), 4)
    return round(count * CANONICAL_COST_1K_USD, 4)


def sanitize_canonical_metadata(metadata: dict) -> dict:
    sanitized = dict(metadata)
    sanitized.pop("prompt_text", None)
    if GEMINI_API_KEY_ENV in json.dumps(sanitized):
        sanitized = json.loads(json.dumps(sanitized).replace(GEMINI_API_KEY_ENV, "<api-key-env>"))
    return sanitized
