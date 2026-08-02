"""Deterministic mirror-selfie crop and blur-only background refocus for review candidates.

Pipeline (``refocus_method: blur_only_v2``):

1. Derive person bbox from garment-union localization (+ deterministic padding).
2. Validate mask quality (coverage, vertical extent, garment containment).
3. On incomplete/torso-only masks, recover bbox via Qwen full-person localization,
   merge with garment union, and re-segment with SAM.
4. Compute aspect-safe portrait crop from mask + bbox bounds.
5. Render ``crop_only`` and blur-only ``crop_refocused`` (background color/brightness
   preserved; spatial blur only).
6. Assess review metrics; recommend ``crop_refocused`` or fallback ``crop_only``.

Bench outputs: ``bench/selfie_refocus/candidates/``. Final deliverable:
``final_selfies/`` via ``cloth-store-selfie-final-packaging``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from cloth_store.catalog_cutouts import expand_bounds, foreground_bounds
from cloth_store.catalog_hash import sha256_file
from cloth_store.catalog_paths import resolve_fixture_source_path, resolve_plan1_fixtures
from cloth_store.sam_masks import (
    DEFAULT_PAD_FRACTION,
    Sam3Session,
    build_sam3_session,
    garment_roles,
    load_font,
    load_localization_json,
    normalized_xyxy_to_pixel_box,
    normalized_xyxy_to_pixel_crop,
    original_box_to_crop_prompt,
    pad_normalized_box,
    place_crop_mask_in_full_image,
    save_binary_mask,
)
from cloth_store.vlm_bbox import LAYOUT_SEPARATES

DEFAULT_OUTPUT_ROOT = Path("bench/selfie_refocus/candidates")
DEFAULT_JSON_DIR = Path("bench/plan1_localization/outputs")

PERSON_TEXT_PROMPT = "person reflected in the mirror"
PERSON_ROLE = "person"

# Portrait review aspect ratios (width / height).
PRIMARY_ASPECT = 4 / 5
FALLBACK_ASPECT = 3 / 4

# Person bbox derivation from garment localization (deterministic heuristic).
HEAD_EXTENSION_FRACTION = 0.20
SIDE_EXTENSION_FRACTION = 0.14
FEET_EXTENSION_FRACTION = 0.08

# Safe padding around person mask bounds inside crop.
CROP_PADDING_FRACTION = 0.06

# Background refocus — blur-only; preserve original color and brightness.
BLUR_RADIUS_PX = 8
FEATHER_RADIUS_PX = 5
MASK_DILATE_PX = 2
REFOCUS_METHOD = "blur_only_v2"

REVIEW_HALO_THRESHOLD = 0.08
REVIEW_PRESERVATION_THRESHOLD = 0.98
REVIEW_BBOX_CONFIDENCE_THRESHOLD = 0.60
REVIEW_MASK_COVERAGE_THRESHOLD = 0.05

# Incomplete/torso-only SAM mask detection and Qwen full-person recovery.
QWEN_FULL_PERSON_PROVENANCE = "qwen_full_reflected_person_v1"
INCOMPLETE_MASK_HEAD_COVERAGE_MAX = 0.02
INCOMPLETE_MASK_LOWER_COVERAGE_MAX = 0.05
INCOMPLETE_MASK_TORSO_COVERAGE_MIN = 0.005
GARMENT_MASK_CONTAINMENT_MIN = 0.70
MASK_VERTICAL_EXTENT_MIN = 0.45
MASK_RECOVERY_HALO_THRESHOLD = REVIEW_HALO_THRESHOLD


@dataclass(frozen=True)
class PersonBboxResult:
    box: list[float]
    provenance: str
    confidence: float
    source_roles: list[str]


@dataclass(frozen=True)
class PortraitCropSpec:
    x0: int
    y0: int
    x1: int
    y1: int
    aspect_ratio: float
    aspect_label: str
    padding_fraction: float
    output_width: int
    output_height: int


@dataclass(frozen=True)
class RefocusMetrics:
    subject_clipped: bool
    retained_background_fraction: float
    background_reduction_fraction: float
    person_mask_coverage: float
    person_pixel_preservation: float
    edge_halo_score: float
    background_color_preservation: float
    background_luminance_preservation: float


@dataclass(frozen=True)
class FixtureRefocusResult:
    fixture_id: str
    source_path: str
    source_sha256: str
    person_bbox: PersonBboxResult
    crop: PortraitCropSpec
    metrics: RefocusMetrics
    variant_paths: dict[str, str]
    mask_path: str
    overlay_path: str
    metadata_path: str
    review_required: bool = False
    review_reason: str | None = None
    recommended_variant: str = "crop_refocused"
    generated_or_reused: str = "processed"


@dataclass(frozen=True)
class BatchRefocusResult:
    processed: tuple[str, ...]
    reused: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    review_required: tuple[str, ...]
    results: tuple[FixtureRefocusResult, ...]


def load_fixture_metadata(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def assess_review_required(
    *,
    person_bbox: PersonBboxResult | dict[str, Any],
    metrics: RefocusMetrics | dict[str, Any],
) -> tuple[bool, str | None]:
    if isinstance(person_bbox, PersonBboxResult):
        confidence = person_bbox.confidence
    else:
        confidence = float(person_bbox.get("confidence", 0.0))
    if isinstance(metrics, RefocusMetrics):
        subject_clipped = metrics.subject_clipped
        edge_halo_score = metrics.edge_halo_score
        person_pixel_preservation = metrics.person_pixel_preservation
        person_mask_coverage = metrics.person_mask_coverage
    else:
        subject_clipped = bool(metrics.get("subject_clipped"))
        edge_halo_score = float(metrics.get("edge_halo_score", 0.0))
        person_pixel_preservation = float(metrics.get("person_pixel_preservation", 1.0))
        person_mask_coverage = float(metrics.get("person_mask_coverage", 1.0))

    if confidence < REVIEW_BBOX_CONFIDENCE_THRESHOLD:
        return True, "low_bbox_confidence"
    if subject_clipped:
        return True, "subject_clipped"
    if edge_halo_score > REVIEW_HALO_THRESHOLD:
        return True, "edge_halo"
    if person_pixel_preservation < REVIEW_PRESERVATION_THRESHOLD:
        return True, "person_preservation"
    if person_mask_coverage < REVIEW_MASK_COVERAGE_THRESHOLD:
        return True, "low_mask_coverage"
    return False, None


def metadata_reuse_eligible(
    metadata: dict[str, Any],
    *,
    source_path: Path,
    localization_path: Path | None = None,
) -> bool:
    params = metadata.get("parameters", {})
    if params.get("refocus_method") != REFOCUS_METHOD:
        return False
    if metadata.get("source_sha256") != sha256_file(source_path):
        return False
    if localization_path is not None:
        expected = metadata.get("localization_sha256")
        if expected and expected != sha256_file(localization_path):
            return False
    for key in ("crop_only", "crop_refocused"):
        rel = metadata.get("variants", {}).get(key)
        if not rel:
            return False
    mask_rel = metadata.get("artifacts", {}).get("person_mask")
    return bool(mask_rel)


def _metadata_paths_valid(metadata: dict[str, Any], repo_root: Path) -> bool:
    for key in ("crop_only", "crop_refocused"):
        rel = metadata.get("variants", {}).get(key)
        if not rel or not (repo_root / rel).is_file():
            return False
    mask_rel = metadata.get("artifacts", {}).get("person_mask")
    if not mask_rel or not (repo_root / mask_rel).is_file():
        return False
    stored_hashes = metadata.get("variant_sha256", {})
    for key in ("crop_only", "crop_refocused"):
        rel = metadata["variants"][key]
        path = repo_root / rel
        expected = stored_hashes.get(key)
        if expected and sha256_file(path) != expected:
            return False
    return True


def _result_from_metadata(metadata: dict[str, Any], *, metadata_path: Path) -> FixtureRefocusResult:
    person_bbox_payload = metadata["person_bbox"]
    person_bbox = PersonBboxResult(
        box=[float(v) for v in person_bbox_payload["box"]],
        provenance=str(person_bbox_payload["provenance"]),
        confidence=float(person_bbox_payload["confidence"]),
        source_roles=list(person_bbox_payload.get("source_roles", [])),
    )
    crop_payload = metadata["crop"]
    crop = PortraitCropSpec(
        x0=int(crop_payload["x0"]),
        y0=int(crop_payload["y0"]),
        x1=int(crop_payload["x1"]),
        y1=int(crop_payload["y1"]),
        aspect_ratio=float(crop_payload["aspect_ratio"]),
        aspect_label=str(crop_payload["aspect_label"]),
        padding_fraction=float(crop_payload["padding_fraction"]),
        output_width=int(crop_payload["output_width"]),
        output_height=int(crop_payload["output_height"]),
    )
    metrics_payload = metadata["metrics"]
    metrics = RefocusMetrics(**metrics_payload)
    review_required = bool(metadata.get("review_required"))
    review_reason = metadata.get("review_reason")
    if not review_required:
        review_required, review_reason = assess_review_required(
            person_bbox=person_bbox,
            metrics=metrics,
        )
    recommended = metadata.get("recommended_variant") or _recommend_variant(metrics)
    if review_required and recommended == "crop_refocused":
        recommended = "crop_only"
    return FixtureRefocusResult(
        fixture_id=metadata["fixture_id"],
        source_path=str(metadata.get("source_path", "")),
        source_sha256=metadata["source_sha256"],
        person_bbox=person_bbox,
        crop=crop,
        metrics=metrics,
        variant_paths=dict(metadata.get("variants", {})),
        mask_path=str(metadata.get("artifacts", {}).get("person_mask", "")),
        overlay_path=str(metadata.get("artifacts", {}).get("bbox_mask_overlay", "")),
        metadata_path=str(metadata_path),
        review_required=review_required,
        review_reason=review_reason,
        recommended_variant=recommended,
        generated_or_reused=str(metadata.get("generated_or_reused", "reused")),
    )


def union_normalized_boxes(boxes: list[list[float]]) -> list[float]:
    if not boxes:
        raise ValueError("cannot union empty box list")
    x_min = min(box[0] for box in boxes)
    y_min = min(box[1] for box in boxes)
    x_max = max(box[2] for box in boxes)
    y_max = max(box[3] for box in boxes)
    return [x_min, y_min, x_max, y_max]


def derive_person_bbox_from_localization(
    localization: dict[str, Any],
    *,
    head_extension: float = HEAD_EXTENSION_FRACTION,
    side_extension: float = SIDE_EXTENSION_FRACTION,
    feet_extension: float = FEET_EXTENSION_FRACTION,
) -> PersonBboxResult:
    """Expand garment union bbox to approximate full visible person."""
    roles = garment_roles(localization)
    boxes = [localization[role] for role in roles]
    union = union_normalized_boxes(boxes)
    x_min, y_min, x_max, y_max = union
    width = x_max - x_min
    height = y_max - y_min

    x_min = max(0.0, x_min - width * side_extension)
    x_max = min(1.0, x_max + width * side_extension)
    y_min = max(0.0, y_min - height * head_extension)
    y_max = min(1.0, y_max + height * feet_extension)

    # Confidence scales with garment coverage and layout completeness.
    area = max(1e-6, (x_max - x_min) * (y_max - y_min))
    role_coverage = len(roles) / (2 if localization["layout"] == LAYOUT_SEPARATES else 1)
    confidence = round(min(0.95, 0.55 + 0.20 * role_coverage + 0.10 * min(1.0, area * 4)), 3)

    return PersonBboxResult(
        box=[x_min, y_min, x_max, y_max],
        provenance="garment_union_asymmetric_v1",
        confidence=confidence,
        source_roles=roles,
    )


def _pixel_box_int(
    box: list[float],
    *,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = normalized_xyxy_to_pixel_box(
        box,
        image_width=image_width,
        image_height=image_height,
    )
    return int(x0), int(y0), int(x1), int(y1)


def analyze_mask_body_coverage(
    person_mask: np.ndarray,
    person_bbox: list[float],
    *,
    image_width: int,
    image_height: int,
) -> dict[str, float]:
    """Estimate mask coverage across coarse vertical body bands inside person bbox."""
    x0, y0, x1, y1 = _pixel_box_int(
        person_bbox,
        image_width=image_width,
        image_height=image_height,
    )
    region = person_mask[y0:y1, x0:x1]
    if region.size == 0:
        return {
            "head_hair": 0.0,
            "torso": 0.0,
            "dress_legs": 0.0,
            "feet": 0.0,
        }

    height = region.shape[0]
    bands = (
        ("head_hair", 0.0, 0.20),
        ("torso", 0.20, 0.55),
        ("dress_legs", 0.55, 0.85),
        ("feet", 0.85, 1.0),
    )
    coverage: dict[str, float] = {}
    for name, start_frac, end_frac in bands:
        start = int(round(height * start_frac))
        end = max(start + 1, int(round(height * end_frac)))
        band = region[start:end, :]
        coverage[name] = round(float(band.sum()) / max(1, band.size), 4)
    return coverage


def garment_union_normalized_box(localization: dict[str, Any]) -> list[float]:
    roles = garment_roles(localization)
    return union_normalized_boxes([localization[role] for role in roles])


def mask_garment_containment(
    person_mask: np.ndarray,
    localization: dict[str, Any],
    *,
    image_width: int,
    image_height: int,
) -> float:
    """Fraction of garment-union bbox pixels covered by the person mask."""
    union = garment_union_normalized_box(localization)
    x0, y0, x1, y1 = _pixel_box_int(
        union,
        image_width=image_width,
        image_height=image_height,
    )
    region = person_mask[y0:y1, x0:x1]
    if region.size == 0:
        return 0.0
    return float(region.sum()) / float(region.size)


def is_incomplete_person_mask(
    person_mask: np.ndarray,
    person_bbox: list[float],
    localization: dict[str, Any],
    *,
    image_width: int,
    image_height: int,
) -> tuple[bool, str | None]:
    """Reject masks that cover only torso/stomach or miss garment/head/limb extent."""
    if not person_mask.any():
        return True, "empty_person_mask"

    coverage = analyze_mask_body_coverage(
        person_mask,
        person_bbox,
        image_width=image_width,
        image_height=image_height,
    )
    torso_only = (
        coverage["head_hair"] <= INCOMPLETE_MASK_HEAD_COVERAGE_MAX
        and coverage["dress_legs"] <= INCOMPLETE_MASK_LOWER_COVERAGE_MAX
        and coverage["feet"] <= INCOMPLETE_MASK_LOWER_COVERAGE_MAX
        and coverage["torso"] >= INCOMPLETE_MASK_TORSO_COVERAGE_MIN
    )
    if torso_only:
        return True, "torso_only_mask"

    garment_containment = mask_garment_containment(
        person_mask,
        localization,
        image_width=image_width,
        image_height=image_height,
    )
    if garment_containment < GARMENT_MASK_CONTAINMENT_MIN:
        return True, "incomplete_garment_coverage"

    px0, py0, px1, py1 = _pixel_box_int(
        person_bbox,
        image_width=image_width,
        image_height=image_height,
    )
    mask_bounds = foreground_bounds(person_mask)
    mask_height = mask_bounds[3] - mask_bounds[1]
    person_height = max(1, py1 - py0)
    if mask_height / person_height < MASK_VERTICAL_EXTENT_MIN:
        return True, "insufficient_vertical_extent"

    return False, None


def should_attempt_mask_recovery(
    *,
    person_mask: np.ndarray,
    person_bbox: PersonBboxResult,
    localization: dict[str, Any],
    image_width: int,
    image_height: int,
    edge_halo_score: float | None = None,
) -> tuple[bool, str | None]:
    incomplete, reason = is_incomplete_person_mask(
        person_mask,
        person_bbox.box,
        localization,
        image_width=image_width,
        image_height=image_height,
    )
    if incomplete:
        return True, reason

    px0, py0, px1, py1 = _pixel_box_int(
        person_bbox.box,
        image_width=image_width,
        image_height=image_height,
    )
    person_area = max(1, (px1 - px0) * (py1 - py0))
    mask_in_bbox = person_mask[py0:py1, px0:px1].sum() / person_area
    if mask_in_bbox < REVIEW_MASK_COVERAGE_THRESHOLD:
        return True, "low_mask_coverage"

    if edge_halo_score is not None and edge_halo_score > MASK_RECOVERY_HALO_THRESHOLD:
        return True, "edge_halo"

    return False, None


def enrich_person_bbox_with_garments(
    qwen_box: list[float],
    localization: dict[str, Any],
    *,
    head_extension: float = HEAD_EXTENSION_FRACTION,
    side_extension: float = SIDE_EXTENSION_FRACTION,
    feet_extension: float = FEET_EXTENSION_FRACTION,
) -> PersonBboxResult:
    """Merge Qwen full-person bbox with garment union and deterministic padding."""
    garment_union = garment_union_normalized_box(localization)
    merged = union_normalized_boxes([qwen_box, garment_union])
    x_min, y_min, x_max, y_max = merged
    width = x_max - x_min
    height = y_max - y_min

    x_min = max(0.0, x_min - width * side_extension)
    x_max = min(1.0, x_max + width * side_extension)
    y_min = max(0.0, y_min - height * head_extension)
    y_max = min(1.0, y_max + height * feet_extension)

    roles = garment_roles(localization)
    area = max(1e-6, (x_max - x_min) * (y_max - y_min))
    role_coverage = len(roles) / (2 if localization["layout"] == LAYOUT_SEPARATES else 1)
    confidence = round(min(0.98, 0.70 + 0.15 * role_coverage + 0.05 * min(1.0, area * 4)), 3)

    return PersonBboxResult(
        box=[x_min, y_min, x_max, y_max],
        provenance=QWEN_FULL_PERSON_PROVENANCE,
        confidence=confidence,
        source_roles=roles,
    )


def localize_person_bbox_with_qwen(
    image_path: str | Path,
    localization: dict[str, Any],
    *,
    model_id: str | None = None,
) -> PersonBboxResult:
    from cloth_store.vlm_bbox import DEFAULT_MODEL, localize_full_reflected_person

    payload = localize_full_reflected_person(
        image_path,
        model_id=model_id or DEFAULT_MODEL,
    )
    return enrich_person_bbox_with_garments(payload["person"], localization)


def subject_bounds_for_crop(
    person_mask: np.ndarray,
    person_bbox: list[float],
    *,
    image_width: int,
    image_height: int,
    padding_fraction: float = CROP_PADDING_FRACTION,
) -> tuple[int, int, int, int]:
    """Union mask foreground with person bbox so crop framing survives incomplete masks."""
    bbox_bounds = _pixel_box_int(
        person_bbox,
        image_width=image_width,
        image_height=image_height,
    )
    if person_mask.any():
        mask_bounds = foreground_bounds(person_mask)
        bounds = (
            min(mask_bounds[0], bbox_bounds[0]),
            min(mask_bounds[1], bbox_bounds[1]),
            max(mask_bounds[2], bbox_bounds[2]),
            max(mask_bounds[3], bbox_bounds[3]),
        )
    else:
        bounds = bbox_bounds
    return expand_bounds(
        bounds,
        margin_fraction=padding_fraction,
        image_width=image_width,
        image_height=image_height,
    )


def load_person_bbox_override(path: str | Path) -> PersonBboxResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    box = payload["box"]
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("person bbox override must contain box: [x_min,y_min,x_max,y_max]")
    return PersonBboxResult(
        box=[float(v) for v in box],
        provenance=str(payload.get("provenance", "manual_override")),
        confidence=float(payload.get("confidence", 1.0)),
        source_roles=list(payload.get("source_roles", [])),
    )


def _person_role_mask_predict(
    session: Sam3Session,
    image: Image.Image,
    pixel_box: list[float],
    *,
    role: str,
) -> np.ndarray:
    """SAM predict using person prompt text instead of garment role prompts."""
    from cloth_store.sam_masks import pixel_xyxy_to_normalized_cxcywh, select_role_mask

    crop_w, crop_h = image.size
    state = session.processor.set_image(image)
    state = session.processor.set_text_prompt(prompt=PERSON_TEXT_PROMPT, state=state)
    norm_box = pixel_xyxy_to_normalized_cxcywh(pixel_box, image_width=crop_w, image_height=crop_h)
    state = session.processor.add_geometric_prompt(box=norm_box, label=True, state=state)
    return select_role_mask(state["masks"], state["scores"], role=role)


def segment_person_mask(
    image_path: str | Path,
    person_bbox: list[float],
    *,
    output_path: str | Path | None = None,
    pad_fraction: float = DEFAULT_PAD_FRACTION,
    session: Sam3Session | None = None,
    checkpoint_version: str = "sam3.1",
) -> np.ndarray:
    if session is None:
        session = build_sam3_session(checkpoint_version=checkpoint_version)

    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        padded_box = pad_normalized_box(
            person_bbox,
            pad_fraction=pad_fraction,
            image_width=width,
            image_height=height,
        )
        crop_bounds = normalized_xyxy_to_pixel_crop(
            padded_box,
            image_width=width,
            image_height=height,
        )
        x0, y0, x1, y1 = crop_bounds
        crop = rgb.crop((x0, y0, x1, y1))
        prompt_box = original_box_to_crop_prompt(
            person_bbox,
            crop_bounds,
            image_width=width,
            image_height=height,
        )
        crop_mask = _person_role_mask_predict(session, crop, prompt_box, role=PERSON_ROLE)
        mask = place_crop_mask_in_full_image(
            crop_mask,
            crop_bounds,
            image_width=width,
            image_height=height,
        )

    if output_path is not None:
        save_binary_mask(mask, output_path)
    return mask


def _choose_aspect(
    image_width: int, image_height: int, subject_bounds: tuple[int, int, int, int]
) -> tuple[float, str]:
    """Prefer 4:5 unless subject bounds cannot fit without clipping."""
    sx0, sy0, sx1, sy1 = subject_bounds
    sub_w = sx1 - sx0
    sub_h = sy1 - sy0
    pad_x = int(round(sub_w * CROP_PADDING_FRACTION))
    pad_y = int(round(sub_h * CROP_PADDING_FRACTION))
    needed_w = sub_w + 2 * pad_x
    needed_h = sub_h + 2 * pad_y
    source_aspect = image_width / max(1, image_height)

    for aspect, label in (
        (PRIMARY_ASPECT, "4:5"),
        (FALLBACK_ASPECT, "3:4"),
        (source_aspect, "source"),
    ):
        crop_h = max(needed_h, int(round(needed_w / aspect)))
        crop_w = int(round(crop_h * aspect))
        if crop_w > image_width or crop_h > image_height:
            crop_w = min(crop_w, image_width)
            crop_h = min(crop_h, image_height)
            if crop_w / max(1, crop_h) < aspect:
                crop_w = int(round(crop_h * aspect))
            else:
                crop_h = int(round(crop_w / aspect))
        if (
            crop_w >= needed_w
            and crop_h >= needed_h
            and crop_w <= image_width
            and crop_h <= image_height
        ):
            return aspect, label
    return source_aspect, "source"


def compute_portrait_crop(
    image_width: int,
    image_height: int,
    person_mask: np.ndarray,
    *,
    person_bbox: list[float] | None = None,
    padding_fraction: float = CROP_PADDING_FRACTION,
) -> PortraitCropSpec:
    """Derive a portrait crop containing the full person with head in upper third."""
    if not person_mask.any() and person_bbox is None:
        raise ValueError("empty person mask: cannot compute portrait crop")

    if person_bbox is not None:
        x0, y0, x1, y1 = subject_bounds_for_crop(
            person_mask,
            person_bbox,
            image_width=image_width,
            image_height=image_height,
            padding_fraction=padding_fraction,
        )
    else:
        bounds = foreground_bounds(person_mask)
        x0, y0, x1, y1 = expand_bounds(
            bounds,
            margin_fraction=padding_fraction,
            image_width=image_width,
            image_height=image_height,
        )
    aspect, aspect_label = _choose_aspect(image_width, image_height, (x0, y0, x1, y1))

    sub_cx = (x0 + x1) / 2.0
    sub_cy = (y0 + y1) / 2.0
    sub_w = x1 - x0
    sub_h = y1 - y0

    crop_h = max(sub_h, int(round(sub_w / aspect)))
    crop_w = int(round(crop_h * aspect))
    if crop_w < sub_w:
        crop_w = sub_w
        crop_h = int(round(crop_w / aspect))
    if crop_h < sub_h:
        crop_h = sub_h
        crop_w = int(round(crop_h * aspect))

    crop_w = min(crop_w, image_width)
    crop_h = min(crop_h, image_height)
    if crop_w / crop_h > aspect:
        crop_h = int(round(crop_w / aspect))
    else:
        crop_w = int(round(crop_h * aspect))
    crop_w = min(crop_w, image_width)
    crop_h = min(crop_h, image_height)

    # Head near upper third: place subject vertical center at ~40% from crop top.
    target_subject_y = crop_h * 0.40
    cy0 = int(round(sub_cy - target_subject_y))
    cy1 = cy0 + crop_h
    if cy0 < 0:
        cy0 = 0
        cy1 = crop_h
    if cy1 > image_height:
        cy1 = image_height
        cy0 = cy1 - crop_h
        if cy0 < 0:
            cy0 = 0
            crop_h = cy1 - cy0

    cx0 = int(round(sub_cx - crop_w / 2.0))
    cx1 = cx0 + crop_w
    if cx0 < 0:
        cx0 = 0
        cx1 = crop_w
    if cx1 > image_width:
        cx1 = image_width
        cx0 = cx1 - crop_w
        if cx0 < 0:
            cx0 = 0
            crop_w = cx1 - cx0

    # Ensure subject remains fully inside crop; expand/shift if needed.
    if x0 < cx0:
        shift = x0 - cx0
        cx0 += shift
        cx1 += shift
    if x1 > cx1:
        shift = x1 - cx1
        cx0 += shift
        cx1 += shift
    if y0 < cy0:
        shift = y0 - cy0
        cy0 += shift
        cy1 += shift
    if y1 > cy1:
        shift = y1 - cy1
        cy0 += shift
        cy1 += shift

    cx0 = max(0, min(cx0, image_width - 1))
    cy0 = max(0, min(cy0, image_height - 1))
    cx1 = min(image_width, max(cx0 + 1, cx1))
    cy1 = min(image_height, max(cy0 + 1, cy1))

    return PortraitCropSpec(
        x0=cx0,
        y0=cy0,
        x1=cx1,
        y1=cy1,
        aspect_ratio=round((cx1 - cx0) / (cy1 - cy0), 4),
        aspect_label=aspect_label,
        padding_fraction=padding_fraction,
        output_width=cx1 - cx0,
        output_height=cy1 - cy0,
    )


def build_feathered_alpha(person_mask: np.ndarray) -> np.ndarray:
    mask_u8 = person_mask.astype(np.uint8) * 255
    mask_img = Image.fromarray(mask_u8, mode="L")
    dilated = mask_img.filter(ImageFilter.MaxFilter(MASK_DILATE_PX * 2 + 1))
    alpha_img = dilated.filter(ImageFilter.GaussianBlur(radius=FEATHER_RADIUS_PX))
    return np.asarray(alpha_img, dtype=np.float64) / 255.0


def load_person_mask(path: str | Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("L")) > 127


def apply_background_blur(
    crop_rgb: np.ndarray,
    crop_alpha: np.ndarray,
    *,
    blur_radius_px: float = BLUR_RADIUS_PX,
) -> np.ndarray:
    """Blur background only; preserve person core pixels and background color/brightness."""
    source = crop_rgb.astype(np.float64)
    bg_img = Image.fromarray(crop_rgb.astype(np.uint8), mode="RGB")
    blurred = np.array(
        bg_img.filter(ImageFilter.GaussianBlur(radius=blur_radius_px)), dtype=np.float64
    )

    alpha = crop_alpha[..., None]
    composite = source * alpha + blurred * (1.0 - alpha)
    result = np.clip(np.round(composite), 0, 255).astype(np.uint8)
    core = crop_alpha >= 0.99
    result[core] = crop_rgb[core]
    return result


def render_crop_only(image_rgb: Image.Image, crop: PortraitCropSpec) -> Image.Image:
    return image_rgb.crop((crop.x0, crop.y0, crop.x1, crop.y1))


def render_crop_refocused(
    image_rgb: Image.Image,
    crop: PortraitCropSpec,
    person_mask: np.ndarray,
) -> Image.Image:
    cropped = image_rgb.crop((crop.x0, crop.y0, crop.x1, crop.y1))
    crop_rgb = np.array(cropped.convert("RGB"))
    crop_mask = person_mask[crop.y0 : crop.y1, crop.x0 : crop.x1]
    alpha = build_feathered_alpha(crop_mask)
    refocused = apply_background_blur(crop_rgb, alpha)
    return Image.fromarray(refocused, mode="RGB")


def _rgb_luminance(rgb: np.ndarray) -> np.ndarray:
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def compute_background_color_metrics(
    crop_only_rgb: np.ndarray,
    crop_refocused_rgb: np.ndarray,
    crop_alpha: np.ndarray,
) -> tuple[float, float]:
    """Return color and luminance preservation scores for background pixels (1.0 = unchanged)."""
    background = crop_alpha < 0.05
    if not background.any():
        return 1.0, 1.0

    source_bg = crop_only_rgb[background].astype(np.float64)
    refocus_bg = crop_refocused_rgb[background].astype(np.float64)
    source_mean = source_bg.mean(axis=0)
    refocus_mean = refocus_bg.mean(axis=0)
    color_delta = float(np.linalg.norm(source_mean - refocus_mean) / 255.0)
    source_lum = float(_rgb_luminance(source_bg).mean())
    refocus_lum = float(_rgb_luminance(refocus_bg).mean())
    lum_delta = abs(source_lum - refocus_lum) / 255.0
    return round(max(0.0, 1.0 - color_delta), 4), round(max(0.0, 1.0 - lum_delta), 4)


def compute_metrics(
    *,
    image_width: int,
    image_height: int,
    person_mask: np.ndarray,
    crop: PortraitCropSpec,
    crop_only_rgb: np.ndarray,
    crop_refocused_rgb: np.ndarray,
) -> RefocusMetrics:
    crop_mask = person_mask[crop.y0 : crop.y1, crop.x0 : crop.x1]
    crop_area = crop_mask.size
    person_pixels = int(crop_mask.sum())
    background_pixels = crop_area - person_pixels

    full_background = int((~person_mask).sum())
    original_area = image_width * image_height
    crop_background_fraction = background_pixels / max(1, crop_area)
    original_background_fraction = full_background / max(1, original_area)
    # Approximate scene reduction: less background visible relative to frame.
    background_reduction = 1.0 - (
        crop_background_fraction / max(1e-6, original_background_fraction)
    )

    subject_clipped = bool(
        crop_mask[0, :].any()
        or crop_mask[-1, :].any()
        or crop_mask[:, 0].any()
        or crop_mask[:, -1].any()
    )

    alpha = build_feathered_alpha(crop_mask)
    core = alpha >= 0.95
    if core.any():
        diff = np.abs(
            crop_only_rgb[core].astype(np.int16) - crop_refocused_rgb[core].astype(np.int16)
        )
        person_preservation = float(1.0 - (diff.mean() / 255.0))
    else:
        person_preservation = 1.0

    band = (alpha > 0.05) & (alpha < 0.95)
    if band.any():
        edge_diff = np.abs(
            crop_only_rgb[band].astype(np.int16) - crop_refocused_rgb[band].astype(np.int16)
        ).mean()
        halo_score = float(edge_diff / 255.0)
    else:
        halo_score = 0.0

    color_preservation, lum_preservation = compute_background_color_metrics(
        crop_only_rgb, crop_refocused_rgb, alpha
    )

    return RefocusMetrics(
        subject_clipped=subject_clipped,
        retained_background_fraction=round(crop_background_fraction, 4),
        background_reduction_fraction=round(max(0.0, background_reduction), 4),
        person_mask_coverage=round(person_pixels / max(1, crop_area), 4),
        person_pixel_preservation=round(person_preservation, 4),
        edge_halo_score=round(halo_score, 4),
        background_color_preservation=color_preservation,
        background_luminance_preservation=lum_preservation,
    )


def render_bbox_overlay(
    image_rgb: Image.Image, person_bbox: list[float], person_mask: np.ndarray
) -> Image.Image:
    width, height = image_rgb.size
    base = np.array(image_rgb.convert("RGB"), dtype=np.float32)
    overlay = base.copy()
    color = np.array([64, 220, 120], dtype=np.float32)
    alpha = 0.35
    overlay[person_mask] = overlay[person_mask] * (1.0 - alpha) + color * alpha

    result = Image.fromarray(overlay.astype(np.uint8))
    draw = ImageDraw.Draw(result)
    x0, y0, x1, y1 = normalized_xyxy_to_pixel_box(
        person_bbox, image_width=width, image_height=height
    )
    draw.rectangle([x0, y0, x1, y1], outline=(255, 220, 64), width=3)
    return result


def make_fixture_comparison_sheet(
    *,
    original: Image.Image,
    bbox_overlay: Image.Image,
    crop_only: Image.Image,
    crop_refocused: Image.Image,
    fixture_id: str,
) -> Image.Image:
    label_font = load_font(24)
    panels: list[tuple[str, Image.Image]] = [
        ("original", original),
        ("subject bbox/mask", bbox_overlay),
        ("crop_only", crop_only),
        ("crop_refocused", crop_refocused),
    ]
    thumb_w, thumb_h = 360, 450
    header_h = 32
    margin = 14
    cols = 4
    sheet_w = cols * thumb_w + (cols + 1) * margin
    sheet_h = thumb_h + header_h + 2 * margin + 28
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, margin), fixture_id, fill=(240, 240, 240), font=label_font)

    for index, (label, panel) in enumerate(panels):
        x = margin + index * (thumb_w + margin)
        y = margin + 28
        draw.text((x, y), label, fill=(200, 200, 200), font=label_font)
        resized = panel.copy()
        resized.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        paste_x = x + (thumb_w - resized.width) // 2
        paste_y = y + header_h + (thumb_h - resized.height) // 2
        sheet.paste(resized, (paste_x, paste_y))
    return sheet


def make_recovery_diagnostic_sheet(
    *,
    original: Image.Image,
    old_overlay: Image.Image,
    old_refocused: Image.Image,
    corrected_overlay: Image.Image,
    corrected_refocused: Image.Image,
    fixture_id: str,
) -> Image.Image:
    """Before/after diagnostic: source | old bbox/mask/refocus | corrected bbox/mask/refocus."""
    label_font = load_font(22)
    sub_font = load_font(18)
    thumb_w, thumb_h = 320, 400
    stack_h = thumb_h // 2 - 8
    header_h = 28
    sub_h = 22
    margin = 12
    cols = 3
    sheet_w = cols * thumb_w + (cols + 1) * margin
    sheet_h = thumb_h + header_h + sub_h + 2 * margin + 32
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (margin, margin),
        f"{fixture_id} recovery diagnostic",
        fill=(240, 240, 240),
        font=label_font,
    )

    columns: list[tuple[str, tuple[Image.Image, str | None]]] = [
        ("source", (original, None)),
        ("old bbox/mask/refocus", (old_overlay, "refocus")),
        ("corrected bbox/mask/refocus", (corrected_overlay, "refocus")),
    ]
    refocus_panels = {
        "refocus": {
            "old bbox/mask/refocus": old_refocused,
            "corrected bbox/mask/refocus": corrected_refocused,
        }
    }

    y = margin + 32
    for index, (label, (panel, sub_key)) in enumerate(columns):
        x = margin + index * (thumb_w + margin)
        draw.text((x, y), label, fill=(200, 200, 200), font=label_font)
        panel_y = y + header_h
        resized = panel.copy()
        resized.thumbnail((thumb_w, stack_h), Image.Resampling.LANCZOS)
        paste_x = x + (thumb_w - resized.width) // 2
        sheet.paste(resized, (paste_x, panel_y))

        if sub_key is not None:
            sub_panel = refocus_panels[sub_key][label]
            sub_resized = sub_panel.copy()
            sub_resized.thumbnail((thumb_w, stack_h), Image.Resampling.LANCZOS)
            sub_y = panel_y + stack_h + 8
            draw.text((x, sub_y - sub_h), "refocus", fill=(170, 170, 170), font=sub_font)
            sheet.paste(sub_resized, (x + (thumb_w - sub_resized.width) // 2, sub_y))
    return sheet


def make_combined_comparison_sheet(
    fixture_results: list[tuple[str, Image.Image]],
) -> Image.Image:
    label_font = load_font(26)
    thumb_w, thumb_h = 720, 400
    margin = 16
    sheet_w = thumb_w + 2 * margin
    sheet_h = len(fixture_results) * (thumb_h + 40) + margin
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    y = margin
    for fixture_id, panel in fixture_results:
        draw.text((margin, y), fixture_id, fill=(240, 240, 240), font=label_font)
        y += 30
        resized = panel.copy()
        resized.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        paste_x = margin + (thumb_w - resized.width) // 2
        sheet.paste(resized, (paste_x, y))
        y += thumb_h + margin
    return sheet


def process_fixture(
    fixture_id: str,
    *,
    repo_root: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    json_dir: str | Path = DEFAULT_JSON_DIR,
    person_bbox_override: str | Path | None = None,
    session: Sam3Session | None = None,
    skip_sam: bool = False,
    reuse_mask: bool = False,
    person_mask: np.ndarray | None = None,
    force: bool = False,
) -> FixtureRefocusResult:
    root = Path(repo_root).expanduser().resolve()
    source_path = resolve_fixture_source_path(fixture_id, repo_root=root)
    fixture_dir = Path(output_root) / fixture_id
    fixture_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = fixture_dir / "metadata.json"
    localization_path = Path(json_dir) / f"{fixture_id}.json"

    if not force and metadata_path.is_file():
        existing = load_fixture_metadata(metadata_path)
        if metadata_reuse_eligible(
            existing,
            source_path=source_path,
            localization_path=localization_path if localization_path.is_file() else None,
        ) and _metadata_paths_valid(existing, root):
            result = _result_from_metadata(existing, metadata_path=metadata_path)
            return replace(result, generated_or_reused="reused")

    localization: dict[str, Any] | None = None
    if localization_path.is_file():
        localization = load_localization_json(localization_path)

    if person_bbox_override is not None:
        person_bbox = load_person_bbox_override(person_bbox_override)
    elif localization is not None:
        person_bbox = derive_person_bbox_from_localization(localization)
    else:
        raise ValueError(
            f"missing localization for {fixture_id}: {localization_path} "
            "and no person bbox override"
        )

    with Image.open(source_path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size

        mask_path = fixture_dir / "person_mask.png"
        mask_recovery: dict[str, Any] | None = None
        recovery_diagnostic_path = fixture_dir / "recovery_diagnostic_sheet.jpg"

        if person_mask is None:
            if reuse_mask and mask_path.is_file():
                person_mask = load_person_mask(mask_path)
            elif skip_sam:
                raise ValueError("person_mask required when skip_sam=True and no saved mask exists")
            else:
                person_mask = segment_person_mask(
                    source_path,
                    person_bbox.box,
                    output_path=mask_path,
                    session=session,
                )
        else:
            save_binary_mask(person_mask, mask_path)

        initial_bbox = person_bbox
        initial_mask = person_mask.copy()
        initial_overlay = render_bbox_overlay(rgb, initial_bbox.box, initial_mask)
        initial_crop = compute_portrait_crop(
            width,
            height,
            initial_mask,
            person_bbox=initial_bbox.box,
        )
        initial_refocused = render_crop_refocused(rgb, initial_crop, initial_mask)
        initial_metrics = compute_metrics(
            image_width=width,
            image_height=height,
            person_mask=initial_mask,
            crop=initial_crop,
            crop_only_rgb=np.array(render_crop_only(rgb, initial_crop)),
            crop_refocused_rgb=np.array(initial_refocused),
        )

        if person_bbox_override is None and localization is not None:
            attempt_recovery, recovery_trigger = should_attempt_mask_recovery(
                person_mask=person_mask,
                person_bbox=person_bbox,
                localization=localization,
                image_width=width,
                image_height=height,
                edge_halo_score=initial_metrics.edge_halo_score,
            )
            if attempt_recovery:
                recovered_bbox = localize_person_bbox_with_qwen(source_path, localization)
                recovered_mask = segment_person_mask(
                    source_path,
                    recovered_bbox.box,
                    session=session,
                )
                still_bad, residual_reason = is_incomplete_person_mask(
                    recovered_mask,
                    recovered_bbox.box,
                    localization,
                    image_width=width,
                    image_height=height,
                )
                if still_bad:
                    raise ValueError(f"mask recovery failed for {fixture_id}: {residual_reason}")

                coverage_before = analyze_mask_body_coverage(
                    initial_mask,
                    initial_bbox.box,
                    image_width=width,
                    image_height=height,
                )
                coverage_after = analyze_mask_body_coverage(
                    recovered_mask,
                    recovered_bbox.box,
                    image_width=width,
                    image_height=height,
                )
                corrected_overlay = render_bbox_overlay(rgb, recovered_bbox.box, recovered_mask)
                corrected_crop = compute_portrait_crop(
                    width,
                    height,
                    recovered_mask,
                    person_bbox=recovered_bbox.box,
                )
                corrected_refocused = render_crop_refocused(rgb, corrected_crop, recovered_mask)
                diagnostic = make_recovery_diagnostic_sheet(
                    original=rgb,
                    old_overlay=initial_overlay,
                    old_refocused=initial_refocused,
                    corrected_overlay=corrected_overlay,
                    corrected_refocused=corrected_refocused,
                    fixture_id=fixture_id,
                )
                diagnostic.save(recovery_diagnostic_path, quality=92)

                person_bbox = recovered_bbox
                person_mask = recovered_mask
                save_binary_mask(person_mask, mask_path)
                mask_recovery = {
                    "applied": True,
                    "trigger": recovery_trigger,
                    "initial_person_bbox": asdict(initial_bbox),
                    "recovered_person_bbox": asdict(recovered_bbox),
                    "body_coverage_before": coverage_before,
                    "body_coverage_after": coverage_after,
                    "initial_metrics": asdict(initial_metrics),
                }

        crop = compute_portrait_crop(
            width,
            height,
            person_mask,
            person_bbox=person_bbox.box,
        )
        crop_only = render_crop_only(rgb, crop)
        crop_refocused = render_crop_refocused(rgb, crop, person_mask)
        overlay = render_bbox_overlay(rgb, person_bbox.box, person_mask)

        crop_only_path = fixture_dir / "crop_only.jpg"
        crop_refocused_path = fixture_dir / "crop_refocused.jpg"
        overlay_path = fixture_dir / "bbox_mask_overlay.jpg"
        comparison_path = fixture_dir / "comparison_sheet.jpg"

        crop_only.save(crop_only_path, quality=92)
        crop_refocused.save(crop_refocused_path, quality=92)
        overlay.save(overlay_path, quality=92)

        comparison = make_fixture_comparison_sheet(
            original=rgb,
            bbox_overlay=overlay,
            crop_only=crop_only,
            crop_refocused=crop_refocused,
            fixture_id=fixture_id,
        )
        comparison.save(comparison_path, quality=92)

        metrics = compute_metrics(
            image_width=width,
            image_height=height,
            person_mask=person_mask,
            crop=crop,
            crop_only_rgb=np.array(crop_only),
            crop_refocused_rgb=np.array(crop_refocused),
        )

    review_required, review_reason = assess_review_required(
        person_bbox=person_bbox,
        metrics=metrics,
    )
    recommended = _recommend_variant(metrics)
    if review_required:
        recommended = "crop_only"

    metadata = {
        "fixture_id": fixture_id,
        "source_path": str(
            source_path.relative_to(root) if source_path.is_relative_to(root) else source_path
        ),
        "source_sha256": sha256_file(source_path),
        "localization_sha256": (
            sha256_file(localization_path) if localization_path.is_file() else None
        ),
        "person_bbox": asdict(person_bbox),
        "crop": asdict(crop),
        "metrics": asdict(metrics),
        "review_required": review_required,
        "review_reason": review_reason,
        "recommended_variant": recommended,
        "generated_or_reused": "processed",
        "variants": {
            "crop_only": str(
                crop_only_path.relative_to(root)
                if crop_only_path.is_relative_to(root)
                else crop_only_path
            ),
            "crop_refocused": str(
                crop_refocused_path.relative_to(root)
                if crop_refocused_path.is_relative_to(root)
                else crop_refocused_path
            ),
        },
        "variant_sha256": {
            "crop_only": sha256_file(crop_only_path),
            "crop_refocused": sha256_file(crop_refocused_path),
        },
        "artifacts": {
            "person_mask": str(
                mask_path.relative_to(root) if mask_path.is_relative_to(root) else mask_path
            ),
            "bbox_mask_overlay": str(
                overlay_path.relative_to(root)
                if overlay_path.is_relative_to(root)
                else overlay_path
            ),
            "comparison_sheet": str(
                comparison_path.relative_to(root)
                if comparison_path.is_relative_to(root)
                else comparison_path
            ),
        },
        "parameters": {
            "refocus_method": REFOCUS_METHOD,
            "primary_aspect": "4:5",
            "fallback_aspect": "3:4",
            "crop_padding_fraction": CROP_PADDING_FRACTION,
            "blur_radius_px": BLUR_RADIUS_PX,
            "background_brightness": 1.0,
            "background_saturation": 1.0,
            "feather_radius_px": FEATHER_RADIUS_PX,
        },
    }
    if mask_recovery is not None:
        metadata["mask_recovery"] = mask_recovery
        recovery_rel = (
            recovery_diagnostic_path.relative_to(root)
            if recovery_diagnostic_path.is_relative_to(root)
            else recovery_diagnostic_path
        )
        metadata["artifacts"]["recovery_diagnostic_sheet"] = str(recovery_rel)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    return FixtureRefocusResult(
        fixture_id=fixture_id,
        source_path=str(source_path),
        source_sha256=metadata["source_sha256"],
        person_bbox=person_bbox,
        crop=crop,
        metrics=metrics,
        variant_paths={
            "crop_only": str(crop_only_path),
            "crop_refocused": str(crop_refocused_path),
        },
        mask_path=str(mask_path),
        overlay_path=str(overlay_path),
        metadata_path=str(metadata_path),
        review_required=review_required,
        review_reason=review_reason,
        recommended_variant=recommended,
        generated_or_reused="processed",
    )


def process_fixtures(
    fixture_ids: list[str],
    *,
    repo_root: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    json_dir: str | Path = DEFAULT_JSON_DIR,
    session: Sam3Session | None = None,
    reuse_mask: bool = False,
    continue_on_error: bool = False,
    force: bool = False,
) -> BatchRefocusResult:
    needs_sam = False
    for fixture_id in fixture_ids:
        fixture_dir = Path(output_root) / fixture_id
        metadata_path = fixture_dir / "metadata.json"
        if force or not metadata_path.is_file():
            needs_sam = True
            break
        root = Path(repo_root).expanduser().resolve()
        source_path = resolve_fixture_source_path(fixture_id, repo_root=root)
        existing = load_fixture_metadata(metadata_path)
        if not metadata_reuse_eligible(existing, source_path=source_path):
            needs_sam = True
            break

    owns_session = session is None and fixture_ids and needs_sam and not reuse_mask
    if owns_session:
        session = build_sam3_session()

    processed: list[str] = []
    reused: list[str] = []
    failed: list[tuple[str, str]] = []
    review_required: list[str] = []
    results: list[FixtureRefocusResult] = []
    comparison_panels: list[tuple[str, Image.Image]] = []

    for fixture_id in fixture_ids:
        try:
            result = process_fixture(
                fixture_id,
                repo_root=repo_root,
                output_root=output_root,
                json_dir=json_dir,
                session=session,
                reuse_mask=reuse_mask,
                force=force,
            )
        except Exception as exc:
            if continue_on_error:
                failed.append((fixture_id, str(exc)))
                continue
            raise

        results.append(result)
        if result.generated_or_reused == "reused":
            reused.append(fixture_id)
        else:
            processed.append(fixture_id)
        if result.review_required:
            review_required.append(fixture_id)

        comparison_path = Path(result.metadata_path).parent / "comparison_sheet.jpg"
        if comparison_path.is_file():
            with Image.open(comparison_path) as sheet:
                comparison_panels.append((fixture_id, sheet.copy()))

    if comparison_panels:
        combined = make_combined_comparison_sheet(comparison_panels)
        combined_path = Path(output_root) / "combined_comparison_sheet.jpg"
        combined.save(combined_path, quality=92)

    summary = {
        "fixture_ids": fixture_ids,
        "output_root": str(output_root),
        "processed": processed,
        "reused": reused,
        "failed": [{"fixture_id": fixture_id, "error": error} for fixture_id, error in failed],
        "review_required": review_required,
        "results": [
            {
                "fixture_id": r.fixture_id,
                "generated_or_reused": r.generated_or_reused,
                "review_required": r.review_required,
                "review_reason": r.review_reason,
                "crop_box": [r.crop.x0, r.crop.y0, r.crop.x1, r.crop.y1],
                "output_size": [r.crop.output_width, r.crop.output_height],
                "aspect_label": r.crop.aspect_label,
                "metrics": asdict(r.metrics),
                "recommended_variant": r.recommended_variant,
            }
            for r in results
        ],
    }
    summary_path = Path(output_root) / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    return BatchRefocusResult(
        processed=tuple(processed),
        reused=tuple(reused),
        failed=tuple(failed),
        review_required=tuple(review_required),
        results=tuple(results),
    )


def _recommend_variant(metrics: RefocusMetrics) -> str:
    if metrics.edge_halo_score > 0.08 or metrics.person_pixel_preservation < 0.98:
        return "crop_only"
    if (
        metrics.background_reduction_fraction >= 0.15
        and metrics.retained_background_fraction > 0.12
    ):
        return "crop_refocused"
    if metrics.retained_background_fraction <= 0.12:
        return "crop_only"
    return "crop_refocused"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bench-only selfie crop/blur-only background refocus review candidates. "
            "Does not modify source photos or production catalog outputs."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root for fixture source resolution.",
    )
    parser.add_argument(
        "--output-root",
        "-o",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Candidate output root (default: bench/selfie_refocus/candidates).",
    )
    parser.add_argument(
        "--json-dir",
        default=str(DEFAULT_JSON_DIR),
        help="Plan1 localization JSON directory.",
    )
    parser.add_argument(
        "--fixture",
        action="append",
        dest="fixtures",
        help="Fixture id(s) to process, e.g. outfit_1.",
    )
    parser.add_argument(
        "--from-fixture",
        type=int,
        help="Inclusive numeric range start (requires --to-fixture).",
    )
    parser.add_argument(
        "--to-fixture",
        type=int,
        help="Inclusive numeric range end (requires --from-fixture).",
    )
    parser.add_argument(
        "--person-bbox-override",
        help="Optional JSON override for person bbox (reviewable manual correction).",
    )
    parser.add_argument(
        "--reuse-mask",
        action="store_true",
        help="Reuse saved person_mask.png from fixture output dir (skip SAM).",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help="Record failures and continue other fixtures (default: true).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess even when valid blur_only_v2 outputs exist.",
    )
    args = parser.parse_args()

    try:
        if args.from_fixture is not None or args.to_fixture is not None:
            fixture_ids = resolve_plan1_fixtures(
                from_fixture=args.from_fixture,
                to_fixture=args.to_fixture,
            )
        elif args.fixtures:
            fixture_ids = args.fixtures
        else:
            raise ValueError("specify --fixture, or --from-fixture and --to-fixture")

        batch = process_fixtures(
            fixture_ids,
            repo_root=args.repo_root,
            output_root=args.output_root,
            json_dir=args.json_dir,
            reuse_mask=args.reuse_mask,
            continue_on_error=args.continue_on_error,
            force=args.force,
        )
        print(
            f"processed={len(batch.processed)} reused={len(batch.reused)} "
            f"failed={len(batch.failed)} review={len(batch.review_required)}"
        )
        if batch.failed:
            for fixture_id, error in batch.failed:
                print(f"  failed {fixture_id}: {error}", file=sys.stderr)
            raise SystemExit(1)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
