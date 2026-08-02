"""Gemini Nano Banana 2 catalog-generation runner."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from cloth_store.catalog_templates import CANVAS_SIZE as CATALOG_CANVAS_SIZE
from cloth_store.gemini_catalog import (
    GEMINI_API_KEY_ENV,
    NANO_BANANA_2_MODEL_ID,
    RUNNER_MODEL_ID,
    GeminiCatalogConfig,
    build_gemini_client,
)
from cloth_store.gemini_catalog_request import (
    load_request_artifact,
    repo_relative_path,
    sha256_file,
    validate_request_artifact,
)

DEFAULT_OUTPUT_ROOT = Path("bench/catalog_generation/outputs")
SMOKE_ARTIFACT_RELATIVE = Path(
    "bench/catalog_generation/artifacts/outfit_1_top_top_full_sleeve.request.json"
)

REQUEST_ASPECT_RATIO = "1:1"
REQUEST_IMAGE_SIZE = "1K"
REQUEST_RESPONSE_MODALITIES = ("TEXT", "IMAGE")
RESIZE_METHOD = "LANCZOS"
SUPPORTED_IMAGE_SIZES = ("512", "1K")

ImageSize = Literal["512", "1K"]

_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"sk-[0-9A-Za-z]{10,}"),
)


class CatalogGenerationError(RuntimeError):
    """Raised when catalog generation fails."""


@dataclass(frozen=True)
class ExtractedResponseImage:
    image: Image.Image
    mime_type: str | None


@dataclass(frozen=True)
class GenerationOutputs:
    raw_path: Path
    catalog_path: Path
    metadata_path: Path
    metadata: dict[str, Any]

    @property
    def normalized_path(self) -> Path:
        return self.catalog_path


@dataclass(frozen=True)
class ResolutionOutputPaths:
    raw_path: Path
    catalog_path: Path
    metadata_path: Path


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sanitize_api_error(message: str) -> str:
    cleaned = message
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("<redacted>", cleaned)
    if GEMINI_API_KEY_ENV in cleaned:
        cleaned = cleaned.replace(GEMINI_API_KEY_ENV, "<api-key-env>")
    return cleaned


def resolution_slug(image_size: ImageSize) -> str:
    return "512" if image_size == "512" else "1k"


def generation_request_settings(*, model_id: str, image_size: ImageSize) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "response_modalities": list(REQUEST_RESPONSE_MODALITIES),
        "aspect_ratio": REQUEST_ASPECT_RATIO,
        "image_size": image_size,
    }


def output_paths_for_resolution(
    *,
    case_dir: Path,
    role: str,
    image_size: ImageSize,
    legacy_names: bool = False,
) -> ResolutionOutputPaths:
    if legacy_names:
        return ResolutionOutputPaths(
            raw_path=case_dir / f"{role}_raw.png",
            catalog_path=case_dir / f"{role}.png",
            metadata_path=case_dir / f"{role}.run.json",
        )
    slug = resolution_slug(image_size)
    catalog_name = f"{role}_{slug}.png" if image_size == "512" else f"{role}_{slug}_to512.png"
    return ResolutionOutputPaths(
        raw_path=case_dir / f"{role}_{slug}_raw.png",
        catalog_path=case_dir / catalog_name,
        metadata_path=case_dir / f"{role}_{slug}.run.json",
    )


def build_generation_contents(*, artifact: dict[str, Any], repo_root: Path) -> list[Any]:
    images = sorted(artifact["images"], key=lambda record: record["order"])
    contents: list[Any] = []
    for record in images:
        label = f"Image {record['order']} ({record['role']}): {record['description']}"
        contents.append(label)
        with Image.open(repo_root / record["path"]) as image:
            contents.append(image.convert("RGB"))
    contents.append(artifact["prompt"])
    return contents


def extract_response_images(response: Any) -> list[ExtractedResponseImage]:
    parts: list[Any] = []
    if hasattr(response, "parts") and response.parts is not None:
        parts.extend(response.parts)
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        candidate_parts = getattr(content, "parts", None)
        if candidate_parts:
            parts.extend(candidate_parts)

    extracted: list[ExtractedResponseImage] = []
    seen_ids: set[int] = set()
    for part in parts:
        part_id = id(part)
        if part_id in seen_ids:
            continue
        seen_ids.add(part_id)

        inline_data = getattr(part, "inline_data", None)
        if inline_data is not None and getattr(inline_data, "data", None):
            mime_type = getattr(inline_data, "mime_type", None)
            image = Image.open(io.BytesIO(inline_data.data))
            extracted.append(ExtractedResponseImage(image=image, mime_type=mime_type))
            continue

        as_image = getattr(part, "as_image", None)
        if callable(as_image):
            image = as_image()
            if image is not None:
                extracted.append(ExtractedResponseImage(image=image, mime_type="image/png"))

    return extracted


def normalize_catalog_output(
    image: Image.Image,
    *,
    target_size: int = CATALOG_CANVAS_SIZE,
) -> tuple[Image.Image, dict[str, Any]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width != height:
        raise CatalogGenerationError(
            f"expected square API image for lossless normalization, got {width}x{height}"
        )

    if width == target_size and height == target_size:
        return rgb, {
            "resize_applied": False,
            "resize_method": None,
            "source_width": width,
            "source_height": height,
        }

    normalized = rgb.resize((target_size, target_size), Image.Resampling.LANCZOS)
    return normalized, {
        "resize_applied": True,
        "resize_method": RESIZE_METHOD,
        "source_width": width,
        "source_height": height,
    }


def output_dir_for_case(*, output_root: Path, fixture_id: str) -> Path:
    return output_root / RUNNER_MODEL_ID / fixture_id


def build_run_metadata(
    *,
    artifact_path: str,
    artifact: dict[str, Any],
    request_settings: dict[str, Any],
    request_utc: str,
    elapsed_seconds: float,
    raw_path: str,
    raw_width: int,
    raw_height: int,
    raw_sha256: str,
    raw_mime_type: str | None,
    catalog_path: str,
    catalog_sha256: str,
    normalization: dict[str, Any],
    generation_calls: int,
    image_size: ImageSize,
    reused: bool = False,
    reuse_source: str | None = None,
) -> dict[str, Any]:
    prompt = artifact["prompt"]
    case = artifact["case"]
    outputs: dict[str, Any] = {
        "raw": {
            "path": raw_path,
            "width": raw_width,
            "height": raw_height,
            "sha256": raw_sha256,
            "mime_type": raw_mime_type,
        },
        "catalog": {
            "path": catalog_path,
            "width": CATALOG_CANVAS_SIZE,
            "height": CATALOG_CANVAS_SIZE,
            "sha256": catalog_sha256,
            "normalization": normalization,
        },
    }
    if image_size == "1K":
        outputs["comparison_512"] = outputs["catalog"]
    else:
        outputs["native_512"] = outputs["catalog"]

    metadata = {
        "artifact_path": artifact_path,
        "request_utc": request_utc,
        "elapsed_seconds": elapsed_seconds,
        "generation_calls": generation_calls,
        "reused": reused,
        "model_id": request_settings["model_id"],
        "runner_model_id": RUNNER_MODEL_ID,
        "case": case,
        "template_id": artifact["template_id"],
        "prompt_sha256": sha256_text(prompt),
        "prompt_text": prompt,
        "input_images": [
            {
                "order": record["order"],
                "role": record["role"],
                "path": record["path"],
                "sha256": record["sha256"],
            }
            for record in sorted(artifact["images"], key=lambda item: item["order"])
        ],
        "request_settings": request_settings,
        "outputs": outputs,
    }
    if reuse_source is not None:
        metadata["reuse_source"] = reuse_source
    return metadata


def serialize_run_metadata(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def save_generation_outputs(
    *,
    repo_root: Path,
    artifact: dict[str, Any],
    artifact_path: Path,
    raw_image: Image.Image,
    raw_mime_type: str | None,
    normalization: dict[str, Any],
    catalog_image: Image.Image,
    request_settings: dict[str, Any],
    request_utc: str,
    elapsed_seconds: float,
    generation_calls: int,
    image_size: ImageSize,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    legacy_names: bool = False,
    reused: bool = False,
    reuse_source: str | None = None,
) -> GenerationOutputs:
    case = artifact["case"]
    fixture_id = case["fixture"]
    role = case["role"]
    case_dir = output_dir_for_case(output_root=repo_root / output_root, fixture_id=fixture_id)
    case_dir.mkdir(parents=True, exist_ok=True)

    paths = output_paths_for_resolution(
        case_dir=case_dir,
        role=role,
        image_size=image_size,
        legacy_names=legacy_names,
    )

    raw_image.save(paths.raw_path, format="PNG")
    catalog_image.save(paths.catalog_path, format="PNG")

    metadata = build_run_metadata(
        artifact_path=repo_relative_path(artifact_path, repo_root=repo_root),
        artifact=artifact,
        request_settings=request_settings,
        request_utc=request_utc,
        elapsed_seconds=elapsed_seconds,
        raw_path=repo_relative_path(paths.raw_path, repo_root=repo_root),
        raw_width=raw_image.width,
        raw_height=raw_image.height,
        raw_sha256=sha256_file(paths.raw_path),
        raw_mime_type=raw_mime_type,
        catalog_path=repo_relative_path(paths.catalog_path, repo_root=repo_root),
        catalog_sha256=sha256_file(paths.catalog_path),
        normalization=normalization,
        generation_calls=generation_calls,
        image_size=image_size,
        reused=reused,
        reuse_source=reuse_source,
    )
    paths.metadata_path.write_text(serialize_run_metadata(metadata), encoding="utf-8")
    return GenerationOutputs(
        raw_path=paths.raw_path,
        catalog_path=paths.catalog_path,
        metadata_path=paths.metadata_path,
        metadata=metadata,
    )


def metadata_matches_artifact(metadata: dict[str, Any], artifact: dict[str, Any]) -> bool:
    if metadata.get("model_id") != artifact.get("gemini_model_id", NANO_BANANA_2_MODEL_ID):
        return False
    if metadata.get("prompt_sha256") != sha256_text(artifact["prompt"]):
        return False
    if metadata.get("template_id") != artifact.get("template_id"):
        return False
    settings = metadata.get("request_settings", {})
    if settings.get("aspect_ratio") != REQUEST_ASPECT_RATIO:
        return False
    if settings.get("response_modalities") != list(REQUEST_RESPONSE_MODALITIES):
        return False
    recorded_inputs = {
        (item["order"], item["role"], item["path"], item["sha256"])
        for item in metadata.get("input_images", [])
    }
    expected_inputs = {
        (item["order"], item["role"], item["path"], item["sha256"])
        for item in artifact.get("images", [])
    }
    return recorded_inputs == expected_inputs


def load_existing_result_metadata(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_catalog_generation(
    *,
    repo_root: Path,
    artifact_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    config: GeminiCatalogConfig | None = None,
    client: Any | None = None,
    cutout_root: Path | None = None,
    template_root: Path | None = None,
    now: datetime | None = None,
    image_size: ImageSize = REQUEST_IMAGE_SIZE,
    legacy_names: bool = False,
) -> GenerationOutputs:
    from google.genai import types

    artifact = load_request_artifact(artifact_path)
    validate_kwargs: dict[str, Any] = {"repo_root": repo_root}
    if cutout_root is not None:
        validate_kwargs["cutout_root"] = cutout_root
    if template_root is not None:
        validate_kwargs["template_root"] = template_root
    validate_request_artifact(artifact, **validate_kwargs)

    model_id = artifact.get("gemini_model_id", NANO_BANANA_2_MODEL_ID)
    if model_id != NANO_BANANA_2_MODEL_ID:
        raise CatalogGenerationError(
            f"artifact model {model_id!r} does not match expected {NANO_BANANA_2_MODEL_ID!r}"
        )

    resolved_config = config or GeminiCatalogConfig(model_id=model_id)
    gemini_client = client or build_gemini_client(config=resolved_config)
    contents = build_generation_contents(artifact=artifact, repo_root=repo_root)
    request_settings = generation_request_settings(model_id=model_id, image_size=image_size)
    request_utc = (now or datetime.now(tz=UTC)).isoformat()

    started = time.perf_counter()
    try:
        response = gemini_client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=list(REQUEST_RESPONSE_MODALITIES),
                image_config=types.ImageConfig(
                    aspect_ratio=REQUEST_ASPECT_RATIO,
                    image_size=image_size,
                ),
            ),
        )
    except Exception as exc:
        raise CatalogGenerationError(sanitize_api_error(str(exc))) from exc
    elapsed = time.perf_counter() - started

    images = extract_response_images(response)
    if not images:
        raise CatalogGenerationError("API response contained no image parts")

    raw = images[0]
    catalog_image, normalization = normalize_catalog_output(raw.image)
    return save_generation_outputs(
        repo_root=repo_root,
        artifact=artifact,
        artifact_path=artifact_path,
        raw_image=raw.image.convert("RGB"),
        raw_mime_type=raw.mime_type,
        normalization=normalization,
        catalog_image=catalog_image,
        request_settings=request_settings,
        request_utc=request_utc,
        elapsed_seconds=elapsed,
        generation_calls=1,
        image_size=image_size,
        output_root=output_root,
        legacy_names=legacy_names,
    )


def validate_output_files(outputs: GenerationOutputs) -> None:
    for path in (outputs.raw_path, outputs.catalog_path, outputs.metadata_path):
        if not path.is_file():
            raise CatalogGenerationError(f"expected output file missing: {path}")

    with Image.open(outputs.catalog_path) as catalog:
        if catalog.size != (CATALOG_CANVAS_SIZE, CATALOG_CANVAS_SIZE):
            raise CatalogGenerationError(
                f"catalog output must be {CATALOG_CANVAS_SIZE}x{CATALOG_CANVAS_SIZE}"
            )
        if catalog.mode != "RGB":
            raise CatalogGenerationError("catalog output must be RGB")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one Nano Banana 2 catalog-generation smoke call from a request artifact."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=SMOKE_ARTIFACT_RELATIVE,
        help="Request artifact path relative to repo root.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Generation output root relative to repo root.",
    )
    parser.add_argument(
        "--image-size",
        choices=SUPPORTED_IMAGE_SIZES,
        default=REQUEST_IMAGE_SIZE,
        help="Native Gemini image_size setting.",
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        help="Optional dotenv credentials file when GEMINI_API_KEY is unset.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    artifact_path = args.artifact
    if not artifact_path.is_absolute():
        artifact_path = repo_root / artifact_path

    config = GeminiCatalogConfig(credentials_file=args.credentials_file)
    try:
        outputs = run_catalog_generation(
            repo_root=repo_root,
            artifact_path=artifact_path,
            output_root=args.output_root,
            config=config,
            image_size=args.image_size,
            legacy_names=True,
        )
        validate_output_files(outputs)
    except CatalogGenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    metadata = outputs.metadata
    print(f"ok: generation succeeded in {metadata['elapsed_seconds']:.1f}s")
    print(
        f"  raw: {metadata['outputs']['raw']['path']} "
        f"{metadata['outputs']['raw']['width']}x{metadata['outputs']['raw']['height']}"
    )
    print(
        f"  catalog: {metadata['outputs']['catalog']['path']} "
        f"{metadata['outputs']['catalog']['width']}x{metadata['outputs']['catalog']['height']}"
    )
    print(f"  metadata: {repo_relative_path(outputs.metadata_path, repo_root=repo_root)}")
    print(f"  generation_calls: {metadata['generation_calls']}")


if __name__ == "__main__":
    main()
