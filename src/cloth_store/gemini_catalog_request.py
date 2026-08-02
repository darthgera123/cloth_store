"""Deterministic Gemini catalog-generation request artifacts (Step 2)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from cloth_store.catalog_detail_crop import (
    DEFAULT_DETAIL_CROP_ROOT,
    DetailCropResult,
    detail_crop_output_path,
    extract_detail_crop,
)
from cloth_store.catalog_hash import sha256_file
from cloth_store.catalog_paths import (
    DEFAULT_CUTOUT_ROOT,
    DEFAULT_TEMPLATE_ROOT,
    catalog_cutout_path,
    template_png_path,
)
from cloth_store.catalog_template_selector import (
    DEFAULT_GARMENT_ATTRIBUTES,
    TemplateSelection,
    garment_attributes_for_case,
    load_garment_attributes,
    select_template_from_attributes,
)
from cloth_store.catalog_templates import CANVAS_SIZE as TEMPLATE_CANVAS_SIZE
from cloth_store.gemini_catalog import NANO_BANANA_2_MODEL_ID, RUNNER_MODEL_ID

ARTIFACT_VERSION = 1
DEFAULT_ARTIFACT_ROOT = Path("bench/catalog_generation/artifacts")

SMOKE_FIXTURE_ID = "outfit_1"
SMOKE_ROLE = "top"
SMOKE_TEMPLATE_ID = "top_full_sleeve"

ALLOWED_CUTOUT_PREFIX = "bench/plan1_localization/outputs/catalog_cutouts/"
ALLOWED_TEMPLATE_PREFIX = "bench/catalog_templates/generated/"
ALLOWED_DETAIL_PREFIX = "bench/catalog_generation/detail_crops/"

FORBIDDEN_PATH_MARKERS: tuple[str, ...] = (
    "plan2_reconstruction/outputs",
    "template_projection",
    "template_projection_preflight",
    "flux_fill_projection",
    "flux_kontext",
    "simple_template_overlay",
    "_projected",
    "_overlay",
    "_diagnostic",
    "_composited",
    "_preflight",
    "_fill_raw",
    "_tryon",
    "_inpaint",
    "_texture_seed",
    "_mirrored_seed",
)

IMAGE_ROLE_GARMENT_IDENTITY = "garment_identity"
IMAGE_ROLE_TEMPLATE_GEOMETRY = "template_geometry"
IMAGE_ROLE_GARMENT_DETAIL = "garment_detail"

PROMPT_POLICY_VERSION = 5

PROMPT_REQUIRED_PHRASES: tuple[str, ...] = (
    "Image 1",
    "Image 2",
    "512",
    "white background",
    "silhouette",
    "color",
    "material",
    "missing",
    "occluded",
    "person",
    "mannequin",
    "hanger",
    "gray template",
    "grid",
    "checker",
    "text",
    "shadow",
    "diagnostic",
    "shape",
    "appearance",
    "hands",
    "phone",
    "weave",
    "texture",
    "authoritative",
)

_TOP_SOURCE_DETAIL = (
    "Image 1 is authoritative for exact color, material, weave, pattern, embroidery, lace, "
    "print, trim, buttons, seams, lapels, pockets, and every other surface feature clearly "
    "visible in the segmented source. Preserving source-visible texture and color fidelity "
    "is the highest priority. Do not simplify, replace, or invent texture, hardware, or "
    "details absent from Image 1. Never copy the template gray fill as fabric."
)

_TEMPLATE_ROLE_POLICIES: dict[str, str] = {
    "top_full_sleeve": (
        "Present a closed, symmetric, front-facing lay-flat garment. Reconstruct any "
        "pose-induced gaps, wrap, or drape from Image 1 as a closed garment. "
        f"{_TOP_SOURCE_DETAIL}"
    ),
    "top_half_sleeve": (
        "Present a closed, symmetric, front-facing lay-flat garment. Reconstruct any "
        "pose-induced gaps, wrap, or drape from Image 1 as a closed garment. "
        f"{_TOP_SOURCE_DETAIL}"
    ),
    "top_sleeveless": (
        "Present a closed, symmetric, front-facing sleeveless blouse or top in a clean "
        "catalog layout. The garment must have clear shoulder straps or upper bodice with "
        "open armholes and no sleeves. Do not add sleeves. Preserve source neckline, straps, "
        "lace, pattern, color, material, and details clearly visible in Image 1. Reconstruct "
        "any pose-induced gaps, wrap, or drape from Image 1 as a closed garment. Do not "
        "present as a structured waistcoat or vest unless Image 1 clearly shows that class. "
        f"{_TOP_SOURCE_DETAIL}"
    ),
    "blazer": (
        "Present a closed, buttoned blazer or suit jacket in a clean front-facing catalog "
        "layout. Reconstruct any pose-induced front opening from Image 1 as closed while "
        "preserving lapels, buttons, pockets, seams, weave, and other jacket-specific "
        "details clearly visible in Image 1. "
        f"{_TOP_SOURCE_DETAIL}"
    ),
    "waistcoat_closed": (
        "Present a closed, buttoned waistcoat or vest in a clean front-facing catalog "
        "layout. The garment must be sleeveless with structured shoulders and armholes. "
        "Reconstruct any pose-induced front opening from Image 1 as closed while preserving "
        "neckline, lapels, buttons, pockets, seams, weave, and other waistcoat-specific "
        "details clearly visible in Image 1. Do not add sleeves, open the front, or invent "
        "unsupported hardware. "
        f"{_TOP_SOURCE_DETAIL}"
    ),
    "pants": (
        "Preserve correct trouser geometry with two distinct legs. Image 1 is authoritative "
        "for color and material. Do not invent pockets, fly, buttons, hardware, center "
        "creases, pressed creases, vertical seams, or texture unless clearly visible in "
        "Image 1."
    ),
    "skirt": (
        "Preserve the correct skirt silhouette. Image 1 is authoritative for color and "
        "material. Use plain solid fabric unless detail is clearly visible in Image 1. Do "
        "not invent pockets, fly, buttons, grommets, plackets, seams, or texture."
    ),
    "skirt_pencil": (
        "Preserve a straight pencil-skirt silhouette with fitted sides and minimal hem "
        "flare. Image 1 is authoritative for color and material. Use plain solid fabric "
        "unless detail is clearly visible in Image 1. Do not invent pockets, fly, buttons, "
        "grommets, plackets, seams, or texture."
    ),
    "skirt_knee_length": (
        "Preserve a knee-length skirt silhouette ending at or just below the knee with "
        "moderate A-line or straight shape as shown in Image 1. Image 1 is authoritative "
        "for color, material, and pattern. Do not invent pockets, fly, buttons, hardware, "
        "or texture unless clearly visible in Image 1."
    ),
    "skirt_long": (
        "Preserve a long or maxi skirt silhouette extending to ankle or floor length with "
        "A-line or straight shape as shown in Image 1. Image 1 is authoritative for color, "
        "material, and pattern. Do not invent pockets, fly, buttons, hardware, or texture "
        "unless clearly visible in Image 1."
    ),
    "dress_knee_length_half_sleeve": (
        "Present a single one-piece dress in a closed, symmetric, front-facing catalog "
        "layout. The garment must be continuous from bodice through skirt with no "
        "blouse-plus-skirt split, no waistband separation, and no invented two-piece "
        "construction. Preserve knee-length hem and half/short sleeves as shown in Image 1. "
        f"{_TOP_SOURCE_DETAIL}"
    ),
    "dress_knee_length_full_sleeve": (
        "Present a single one-piece dress in a closed, symmetric, front-facing catalog "
        "layout. The garment must be continuous from bodice through skirt with no "
        "blouse-plus-skirt split, no waistband separation, and no invented two-piece "
        "construction. Preserve knee-length hem and full/long sleeves as shown in Image 1. "
        f"{_TOP_SOURCE_DETAIL}"
    ),
}

_PROMPT_LEAKAGE_TERMS: tuple[str, ...] = (
    "eyelet",
    "standing collar",
    "gathered cuff",
    "v-neck",
)

_UNIVERSAL_PROMPT_TAIL = (
    "Image 1 is authoritative for visible color, material, and weave. "
    "Ignore hands, phone, and any non-garment segmentation artifacts from Image 1. "
    "The template gray color must never transfer to the output.\n\n"
    "Output a single 512×512 front-facing catalog photograph on a pure white background "
    "(255, 255, 255). Fit the garment to the silhouette of Image 2 while preserving the "
    "color and material of Image 1. Reconstruct only missing or occluded regions implied "
    "by the target silhouette; do not invent new design elements. Exclude any person, "
    "mannequin, hanger, gray template color, grids, checkers, text, shadows, or "
    "diagnostic artifacts. The template controls shape, not appearance."
)


class CatalogRequestArtifactError(ValueError):
    """Raised when a request artifact or its inputs are invalid."""


@dataclass(frozen=True)
class ResolvedImageInput:
    order: int
    role: str
    description: str
    absolute_path: Path
    repo_relative_path: str
    sha256: str
    width: int
    height: int
    mode: str


def repo_relative_path(path: Path, *, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def validate_catalog_image(
    path: Path, *, expected_size: int = TEMPLATE_CANVAS_SIZE
) -> dict[str, Any]:
    if not path.is_file():
        raise CatalogRequestArtifactError(f"image not found: {path}")
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        if width != expected_size or height != expected_size:
            raise CatalogRequestArtifactError(
                f"expected {expected_size}x{expected_size} RGB image at {path}, "
                f"got {width}x{height} {rgb.mode}"
            )
        return {"width": width, "height": height, "mode": "RGB"}


def validate_source_provenance(
    repo_relative: str,
    *,
    image_role: str,
    fixture_id: str,
    role: str,
    template_id: str | None = None,
) -> None:
    posix = repo_relative.replace("\\", "/")
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker in posix:
            raise CatalogRequestArtifactError(
                f"{image_role} path must be a primary Plan 1 cutout or canonical template, "
                f"not a derived experiment output (found {marker!r} in {posix})"
            )

    if image_role == IMAGE_ROLE_GARMENT_IDENTITY:
        expected_suffix = f"/{fixture_id}/catalog_{role}.png"
        if not posix.startswith(ALLOWED_CUTOUT_PREFIX):
            raise CatalogRequestArtifactError(
                f"garment identity path must start with {ALLOWED_CUTOUT_PREFIX}, got {posix}"
            )
        if not posix.endswith(expected_suffix):
            raise CatalogRequestArtifactError(
                f"garment identity path must end with {expected_suffix}, got {posix}"
            )
        return

    if image_role == IMAGE_ROLE_TEMPLATE_GEOMETRY:
        if template_id is None:
            raise CatalogRequestArtifactError("template_id is required for template geometry paths")
        expected = f"{ALLOWED_TEMPLATE_PREFIX}{template_id}.png"
        if posix != expected:
            raise CatalogRequestArtifactError(
                f"template geometry path must be exactly {expected}, got {posix}"
            )
        return

    if image_role == IMAGE_ROLE_GARMENT_DETAIL:
        expected_suffix = f"/{fixture_id}_{role}_detail.png"
        if not posix.startswith(ALLOWED_DETAIL_PREFIX):
            raise CatalogRequestArtifactError(
                f"garment detail path must start with {ALLOWED_DETAIL_PREFIX}, got {posix}"
            )
        if not posix.endswith(expected_suffix):
            raise CatalogRequestArtifactError(
                f"garment detail path must end with {expected_suffix}, got {posix}"
            )
        return

    raise CatalogRequestArtifactError(f"unknown image role: {image_role!r}")


def template_prompt_policy(template_id: str) -> str:
    try:
        return _TEMPLATE_ROLE_POLICIES[template_id]
    except KeyError as exc:
        raise CatalogRequestArtifactError(
            f"unknown template_id for prompt policy: {template_id!r}"
        ) from exc


def build_catalog_generation_prompt(
    *,
    fixture_id: str,
    role: str,
    template_id: str,
    include_detail_reference: bool = False,
) -> str:
    role_policy = template_prompt_policy(template_id)
    detail_clause = ""
    if include_detail_reference:
        detail_clause = (
            "\n\nImage 3 is an optional close-up detail reference cropped from the same "
            "segmented source as Image 1. Use Image 3 only to reinforce exact texture, "
            "weave, pattern, embroidery, and trim visible in the source. Image 3 does not "
            "change the target silhouette."
        )
    return (
        f"Create a catalog product image for fixture {fixture_id} ({role}) using separate "
        "reference images.\n\n"
        "Image 1 is the garment identity reference. "
        f"{role_policy}\n\n"
        f"Image 2 is the geometry and silhouette reference ({template_id}). Use Image 2 only "
        "for garment shape, proportions, sleeve length, hem line, and overall layout. The "
        "flat gray fill in Image 2 is a placeholder silhouette — do not copy that gray color "
        "or treat it as fabric. Image 2 controls shape, not appearance."
        f"{detail_clause}\n\n"
        f"{_UNIVERSAL_PROMPT_TAIL}"
    )


def validate_prompt_constraints(prompt: str) -> None:
    lowered = prompt.lower()
    missing = [phrase for phrase in PROMPT_REQUIRED_PHRASES if phrase.lower() not in lowered]
    if missing:
        raise CatalogRequestArtifactError(
            f"prompt is missing required constraints: {', '.join(missing)}"
        )


def prompt_descriptor_leakage(prompt: str) -> tuple[str, ...]:
    lowered = prompt.lower()
    return tuple(term for term in _PROMPT_LEAKAGE_TERMS if term in lowered)


def resolve_case_image_paths(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    template_id: str,
    cutout_root: Path = DEFAULT_CUTOUT_ROOT,
    template_root: Path = DEFAULT_TEMPLATE_ROOT,
) -> tuple[Path, Path]:
    cutout = repo_root / catalog_cutout_path(
        cutout_root=cutout_root,
        fixture_id=fixture_id,
        role=role,
    )
    template = repo_root / template_png_path(
        template_root=template_root,
        template_id=template_id,
    )
    return cutout, template


def describe_image_input(
    *,
    order: int,
    role: str,
    description: str,
    absolute_path: Path,
    repo_root: Path,
    fixture_id: str,
    case_role: str,
    template_id: str | None = None,
) -> ResolvedImageInput:
    dimensions = validate_catalog_image(absolute_path)
    relative = repo_relative_path(absolute_path, repo_root=repo_root)
    validate_source_provenance(
        relative,
        image_role=role,
        fixture_id=fixture_id,
        role=case_role,
        template_id=template_id,
    )
    return ResolvedImageInput(
        order=order,
        role=role,
        description=description,
        absolute_path=absolute_path,
        repo_relative_path=relative,
        sha256=sha256_file(absolute_path),
        width=dimensions["width"],
        height=dimensions["height"],
        mode=dimensions["mode"],
    )


def resolve_case_template_selection(
    *,
    fixture_id: str,
    role: str,
    template_override: str | None = None,
    attributes_path: Path = DEFAULT_GARMENT_ATTRIBUTES,
) -> TemplateSelection:
    attributes = load_garment_attributes(attributes_path)
    record = garment_attributes_for_case(attributes, fixture=fixture_id, role=role)
    if record is None:
        raise CatalogRequestArtifactError(f"no garment_attributes record for {fixture_id}/{role}")
    return select_template_from_attributes(record, template_override=template_override)


def build_request_artifact(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    template_id: str,
    cutout_root: Path = DEFAULT_CUTOUT_ROOT,
    template_root: Path = DEFAULT_TEMPLATE_ROOT,
    detail_root: Path = DEFAULT_DETAIL_CROP_ROOT,
    template_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cutout_path, template_path = resolve_case_image_paths(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        cutout_root=cutout_root,
        template_root=template_root,
    )

    garment = describe_image_input(
        order=1,
        role=IMAGE_ROLE_GARMENT_IDENTITY,
        description="Plan 1 segmented catalog cutout (identity/color/texture reference)",
        absolute_path=cutout_path,
        repo_root=repo_root,
        fixture_id=fixture_id,
        case_role=role,
    )
    template = describe_image_input(
        order=2,
        role=IMAGE_ROLE_TEMPLATE_GEOMETRY,
        description="Canonical template silhouette (geometry/layout reference)",
        absolute_path=template_path,
        repo_root=repo_root,
        fixture_id=fixture_id,
        case_role=role,
        template_id=template_id,
    )

    detail_result: DetailCropResult | None = None
    if role in {"top", "dress"}:
        detail_abs = repo_root / detail_crop_output_path(
            detail_root=detail_root,
            fixture_id=fixture_id,
            role=role,
        )
        detail_result = extract_detail_crop(cutout_path, output_path=detail_abs)

    include_detail = detail_result is not None and detail_result.included
    prompt = build_catalog_generation_prompt(
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        include_detail_reference=include_detail,
    )
    validate_prompt_constraints(prompt)

    images: list[dict[str, Any]] = [
        {
            "order": garment.order,
            "role": garment.role,
            "description": garment.description,
            "path": garment.repo_relative_path,
            "sha256": garment.sha256,
            "width": garment.width,
            "height": garment.height,
            "mode": garment.mode,
        },
        {
            "order": template.order,
            "role": template.role,
            "description": template.description,
            "path": template.repo_relative_path,
            "sha256": template.sha256,
            "width": template.width,
            "height": template.height,
            "mode": template.mode,
        },
    ]
    part_order = [IMAGE_ROLE_GARMENT_IDENTITY, IMAGE_ROLE_TEMPLATE_GEOMETRY]
    detail_provenance: dict[str, Any] | None = None

    if include_detail and detail_result is not None and detail_result.output_path is not None:
        detail = describe_image_input(
            order=3,
            role=IMAGE_ROLE_GARMENT_DETAIL,
            description=(
                "Source-derived garment detail crop (texture/pattern/trim reinforcement only)"
            ),
            absolute_path=detail_result.output_path,
            repo_root=repo_root,
            fixture_id=fixture_id,
            case_role=role,
        )
        images.append(
            {
                "order": detail.order,
                "role": detail.role,
                "description": detail.description,
                "path": detail.repo_relative_path,
                "sha256": detail.sha256,
                "width": detail.width,
                "height": detail.height,
                "mode": detail.mode,
            }
        )
        part_order.append(IMAGE_ROLE_GARMENT_DETAIL)
        detail_provenance = {
            "included": True,
            "reason": detail_result.reason,
            "source_bbox": detail_result.source_bbox,
            "crop_bbox": detail_result.crop_bbox,
        }
    elif role == "top" and detail_result is not None:
        detail_provenance = {
            "included": False,
            "reason": detail_result.reason,
            "source_bbox": detail_result.source_bbox,
            "crop_bbox": detail_result.crop_bbox,
        }

    payload: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "bench": "catalog_generation",
        "prompt_policy_version": PROMPT_POLICY_VERSION,
        "runner_model_id": RUNNER_MODEL_ID,
        "gemini_model_id": NANO_BANANA_2_MODEL_ID,
        "case": {"fixture": fixture_id, "role": role},
        "template_id": template_id,
        "prompt": prompt,
        "images": images,
        "request_layout": {
            "separate_parts": True,
            "no_composite_input": True,
            "part_order": part_order,
        },
    }
    if template_selection is not None:
        payload["template_selection"] = template_selection
    if detail_provenance is not None:
        payload["detail_reference_provenance"] = detail_provenance
    return payload


def artifact_output_path(
    *,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    fixture_id: str,
    role: str,
    template_id: str,
) -> Path:
    return artifact_root / f"{fixture_id}_{role}_{template_id}.request.json"


def serialize_request_artifact(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_request_artifact(
    payload: dict[str, Any],
    *,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_request_artifact(payload), encoding="utf-8")
    return output_path


def load_request_artifact(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_request_artifact(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    cutout_root: Path = DEFAULT_CUTOUT_ROOT,
    template_root: Path = DEFAULT_TEMPLATE_ROOT,
) -> None:
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        raise CatalogRequestArtifactError("unsupported artifact_version")

    case = payload.get("case")
    if not isinstance(case, dict):
        raise CatalogRequestArtifactError("case must be an object")
    fixture_id = case.get("fixture")
    role = case.get("role")
    template_id = payload.get("template_id")
    if (
        not isinstance(fixture_id, str)
        or not isinstance(role, str)
        or not isinstance(template_id, str)
    ):
        raise CatalogRequestArtifactError(
            "case.fixture, case.role, and template_id must be strings"
        )

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise CatalogRequestArtifactError("prompt must be a non-empty string")
    validate_prompt_constraints(prompt)

    images = payload.get("images")
    if not isinstance(images, list) or len(images) not in (2, 3):
        raise CatalogRequestArtifactError("images must contain two or three entries")

    expected = build_request_artifact(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        cutout_root=cutout_root,
        template_root=template_root,
    )

    if images[0].get("role") != IMAGE_ROLE_GARMENT_IDENTITY:
        raise CatalogRequestArtifactError("first image must be garment_identity")
    if images[1].get("role") != IMAGE_ROLE_TEMPLATE_GEOMETRY:
        raise CatalogRequestArtifactError("second image must be template_geometry")
    if len(images) == 3 and images[2].get("role") != IMAGE_ROLE_GARMENT_DETAIL:
        raise CatalogRequestArtifactError("third image must be garment_detail when present")
    if images[0].get("order") != 1 or images[1].get("order") != 2:
        raise CatalogRequestArtifactError("image order must begin 1 then 2")
    if len(images) == 3 and images[2].get("order") != 3:
        raise CatalogRequestArtifactError("third image order must be 3")

    for index, (record, expected_record) in enumerate(zip(images, expected["images"], strict=True)):
        relative = record.get("path")
        if not isinstance(relative, str):
            raise CatalogRequestArtifactError(f"images[{index}].path must be a string")
        validate_source_provenance(
            relative,
            image_role=record.get("role", ""),
            fixture_id=fixture_id,
            role=role,
            template_id=template_id if index == 1 else None,
        )
        absolute = repo_root / relative
        dimensions = validate_catalog_image(absolute)
        digest = sha256_file(absolute)
        if record.get("sha256") != digest:
            raise CatalogRequestArtifactError(
                f"images[{index}] sha256 mismatch for {relative}: "
                f"artifact has {record.get('sha256')!r}, file has {digest!r}"
            )
        if (
            record.get("width") != dimensions["width"]
            or record.get("height") != dimensions["height"]
        ):
            raise CatalogRequestArtifactError(f"images[{index}] dimensions mismatch for {relative}")
        for field in ("width", "height", "mode", "role", "order", "description"):
            if record.get(field) != expected_record.get(field):
                raise CatalogRequestArtifactError(
                    f"images[{index}].{field} mismatch: "
                    f"artifact={record.get(field)!r}, expected={expected_record.get(field)!r}"
                )

    layout = payload.get("request_layout")
    if not isinstance(layout, dict):
        raise CatalogRequestArtifactError("request_layout must be an object")
    if layout.get("separate_parts") is not True or layout.get("no_composite_input") is not True:
        raise CatalogRequestArtifactError("request_layout must keep images as separate parts")


def build_smoke_request_artifact(
    *,
    repo_root: Path,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    cutout_root: Path = DEFAULT_CUTOUT_ROOT,
    template_root: Path = DEFAULT_TEMPLATE_ROOT,
) -> tuple[dict[str, Any], Path]:
    payload = build_request_artifact(
        repo_root=repo_root,
        fixture_id=SMOKE_FIXTURE_ID,
        role=SMOKE_ROLE,
        template_id=SMOKE_TEMPLATE_ID,
        cutout_root=cutout_root,
        template_root=template_root,
    )
    output_path = artifact_output_path(
        artifact_root=artifact_root,
        fixture_id=SMOKE_FIXTURE_ID,
        role=SMOKE_ROLE,
        template_id=SMOKE_TEMPLATE_ID,
    )
    write_request_artifact(payload, output_path=output_path)
    return payload, output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build or validate a deterministic Gemini catalog-generation request artifact "
            "without calling the API."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory).",
    )
    parser.add_argument("--fixture", default=SMOKE_FIXTURE_ID)
    parser.add_argument("--role", default=SMOKE_ROLE)
    parser.add_argument("--template-id", default=SMOKE_TEMPLATE_ID)
    parser.add_argument(
        "--cutout-root",
        type=Path,
        default=DEFAULT_CUTOUT_ROOT,
        help="Plan 1 catalog cutout root relative to repo root.",
    )
    parser.add_argument(
        "--template-root",
        type=Path,
        default=DEFAULT_TEMPLATE_ROOT,
        help="Canonical template PNG root relative to repo root.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
        help="Directory for request JSON artifacts relative to repo root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional artifact output path relative to repo root.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate an existing artifact instead of rebuilding it.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    artifact_root = repo_root / args.artifact_root
    output_path = (
        repo_root / args.output
        if args.output is not None
        else artifact_output_path(
            artifact_root=artifact_root,
            fixture_id=args.fixture,
            role=args.role,
            template_id=args.template_id,
        )
    )

    try:
        if args.validate_only:
            payload = load_request_artifact(output_path)
            validate_request_artifact(
                payload,
                repo_root=repo_root,
                cutout_root=args.cutout_root,
                template_root=args.template_root,
            )
            print(f"ok: validated {repo_relative_path(output_path, repo_root=repo_root)}")
            raise SystemExit(0)

        payload = build_request_artifact(
            repo_root=repo_root,
            fixture_id=args.fixture,
            role=args.role,
            template_id=args.template_id,
            cutout_root=args.cutout_root,
            template_root=args.template_root,
        )
        write_request_artifact(payload, output_path=output_path)
        validate_request_artifact(
            payload,
            repo_root=repo_root,
            cutout_root=args.cutout_root,
            template_root=args.template_root,
        )
    except CatalogRequestArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    relative = repo_relative_path(output_path, repo_root=repo_root)
    print(f"ok: wrote {relative}")
    for image in payload["images"]:
        print(
            f"  image {image['order']} ({image['role']}): {image['path']} "
            f"sha256={image['sha256'][:12]}…"
        )


if __name__ == "__main__":
    main()
