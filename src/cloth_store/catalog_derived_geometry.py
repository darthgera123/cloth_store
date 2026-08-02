"""Derived geometry validation and prompt builders for production overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from cloth_store.catalog_templates import (
    CANVAS_SIZE,
    SILHOUETTE_FILL,
    WHITE_BACKGROUND,
    template_silhouette_width_metrics,
    visible_foreground_bounds,
)
from cloth_store.catalog_vlm_records import build_vlm_attribute_clause
from cloth_store.gemini_catalog_request import (
    CatalogRequestArtifactError,
    template_prompt_policy,
    validate_prompt_constraints,
)

GEOMETRY_CANDIDATE_NAMESPACE = "outfit_3_top_presentation_geometry_v1"
IMAGE_ROLE_DERIVED_GEOMETRY = "derived_geometry"

ALLOWED_DERIVED_GEOMETRY_PREFIX = "bench/catalog_generation/candidates/"
ALLOWED_GEOMETRY_SOURCE_PREFIX = (
    "bench/catalog_generation/outputs/nano_banana_2/catalog_production_v1/"
)


def _white_distance(pixel: tuple[int, int, int]) -> float:
    r, g, b = pixel
    wr, wg, wb = WHITE_BACKGROUND
    return ((r - wr) ** 2 + (g - wg) ** 2 + (b - wb) ** 2) ** 0.5


def extract_neutral_geometry_silhouette(
    source_path: Path,
    *,
    white_threshold: float = 18.0,
    canvas_size: int = CANVAS_SIZE,
) -> Image.Image:
    """Binary/neutral silhouette from a catalog output (geometry only)."""
    with Image.open(source_path) as image:
        rgb = image.convert("RGB")
        if rgb.size != (canvas_size, canvas_size):
            rgb = rgb.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)

    out = Image.new("RGB", (canvas_size, canvas_size), WHITE_BACKGROUND)
    out_pixels = out.load()
    src_pixels = rgb.load()
    for y in range(canvas_size):
        for x in range(canvas_size):
            if _white_distance(src_pixels[x, y]) > white_threshold:
                out_pixels[x, y] = SILHOUETTE_FILL
    return out


def validate_derived_geometry_image(image: Image.Image) -> dict[str, Any]:
    """Ensure extracted silhouette is neutral binary fill on white."""
    rgb = image.convert("RGB")
    allowed = {WHITE_BACKGROUND, SILHOUETTE_FILL}
    colors = {rgb.getpixel((x, y)) for y in range(rgb.height) for x in range(rgb.width)}
    foreign = colors - allowed
    if foreign:
        raise CatalogRequestArtifactError(
            f"derived geometry must use only white and silhouette fill, found {foreign}"
        )
    try:
        bounds = visible_foreground_bounds(rgb)
    except ValueError as exc:
        raise CatalogRequestArtifactError("derived geometry has no foreground pixels") from exc
    metrics = template_silhouette_width_metrics(rgb)
    if metrics["bbox_width_fraction"] < 0.15:
        raise CatalogRequestArtifactError("derived geometry foreground too small")
    return {
        "foreground_bounds": bounds,
        "width_metrics": metrics,
        "unique_colors": sorted(colors),
    }


def validate_geometry_source_path(repo_relative: str) -> None:
    posix = repo_relative.replace("\\", "/")
    if not posix.startswith(ALLOWED_GEOMETRY_SOURCE_PREFIX):
        raise CatalogRequestArtifactError(
            f"geometry source must start with {ALLOWED_GEOMETRY_SOURCE_PREFIX}, got {posix}"
        )
    if not posix.endswith("_1k_raw.png") and not posix.endswith(".png"):
        raise CatalogRequestArtifactError(f"geometry source must be a PNG catalog output: {posix}")


def validate_derived_geometry_path(repo_relative: str) -> None:
    posix = repo_relative.replace("\\", "/")
    if not posix.startswith(ALLOWED_DERIVED_GEOMETRY_PREFIX):
        raise CatalogRequestArtifactError(
            f"derived geometry path must start with {ALLOWED_DERIVED_GEOMETRY_PREFIX}, got {posix}"
        )


def build_geometry_candidate_prompt(
    *,
    fixture_id: str,
    role: str,
    template_id: str,
    geometry_source_fixture: str,
    attributes: dict[str, dict[str, str]],
    include_detail_reference: bool,
) -> tuple[str, list[str]]:
    role_policy = template_prompt_policy(template_id)
    detail_clause = ""
    if include_detail_reference:
        detail_clause = (
            "\n\nImage 3 is a close-up detail reference cropped from the same segmented "
            "source as Image 1. Use Image 3 only to reinforce exact texture, weave, pattern, "
            "and trim visible in the source. Image 3 does not change the target silhouette."
        )

    base = (
        f"Create a catalog product image for fixture {fixture_id} ({role}) using separate "
        "reference images.\n\n"
        "Image 1 is the garment identity reference. "
        f"{role_policy}\n\n"
        f"Image 2 is a derived neutral geometry and silhouette reference extracted from the "
        f"successful catalog presentation of {geometry_source_fixture} ({role}). Use Image 2 "
        "ONLY for garment shape, proportions, centering within the square frame, scale, body "
        "width and length, sleeve spread angle, hem placement, closed/buttoned front layout, "
        "and overall catalog pose. The flat gray fill in Image 2 is a placeholder silhouette — "
        "do not copy that gray color or treat it as fabric. Image 2 controls geometry and "
        "presentation layout, not appearance.\n\n"
        "CRITICAL appearance constraints: preserve ONLY the black color, matte woven fabric, "
        "notched lapels, buttons, pockets, seams, and construction details clearly visible in "
        "Image 1. Do NOT transfer any white, off-white, cream, ivory, or light-colored fabric "
        f"from {geometry_source_fixture}. Do NOT copy {geometry_source_fixture}'s material, "
        "weave, satin sheen, princess seams, pocket styling, or any other surface feature from "
        "Image 2 or from memory of that reference output. Do NOT convert the blazer to a "
        "round neck, crew neck, collarless top, or blouse. Do NOT invent buttons, hardware, "
        "or pockets absent from Image 1."
        f"{detail_clause}\n\n"
    )

    clause, injected = build_vlm_attribute_clause(attributes)
    tail = (
        f"{clause}\n\n"
        "Image 1 is authoritative for visible color, material, and weave. Ignore hands, phone, "
        "and any non-garment segmentation artifacts from Image 1. The template gray color must "
        "never transfer to the output.\n\n"
        "Output a single 512×512 front-facing catalog photograph on a pure white background "
        "(255, 255, 255). Match the catalog presentation geometry of Image 2 — symmetric "
        "front-facing layout, vertically hanging straight sleeves, slim tailored body, single "
        "closed front, and centered framing — while preserving the black blazer identity of "
        "Image 1. Reconstruct only missing or occluded regions implied by the target silhouette; "
        "do not invent new design elements. Exclude any person, mannequin, hanger, gray template "
        "color, grids, checkers, text, shadows, or diagnostic artifacts. Image 2 controls shape "
        "and presentation; Image 1 controls appearance."
    )
    prompt = base + tail
    validate_prompt_constraints(prompt)
    return prompt, injected
