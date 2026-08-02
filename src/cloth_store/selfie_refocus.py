"""Deterministic mirror-selfie crop and background refocus for review candidates.

Produces portrait reframes that reduce distracting scene content while keeping
person pixels faithful. Outputs live under bench/selfie_refocus/candidates/.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

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

# Background refocus — restrained to avoid halos.
BLUR_RADIUS_PX = 8
BACKGROUND_DIM_FACTOR = 0.88
BACKGROUND_DESATURATION = 0.65
FEATHER_RADIUS_PX = 5
MASK_DILATE_PX = 2

VariantName = Literal["crop_only", "crop_refocused"]


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

    for aspect, label in ((PRIMARY_ASPECT, "4:5"), (FALLBACK_ASPECT, "3:4")):
        crop_h = max(needed_h, int(round(needed_w / aspect)))
        crop_w = int(round(crop_h * aspect))
        if crop_w > image_width or crop_h > image_height:
            crop_w = min(crop_w, image_width)
            crop_h = min(crop_h, image_height)
            if crop_w / crop_h < aspect:
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
    return FALLBACK_ASPECT, "3:4"


def compute_portrait_crop(
    image_width: int,
    image_height: int,
    person_mask: np.ndarray,
    *,
    padding_fraction: float = CROP_PADDING_FRACTION,
) -> PortraitCropSpec:
    """Derive a portrait crop containing the full person with head in upper third."""
    if not person_mask.any():
        raise ValueError("empty person mask: cannot compute portrait crop")

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


def _desaturate_rgb(rgb: np.ndarray, amount: float) -> np.ndarray:
    gray = np.mean(rgb.astype(np.float64), axis=2, keepdims=True)
    return np.clip(rgb * (1.0 - amount) + gray * amount, 0, 255).astype(np.uint8)


def apply_background_refocus(
    crop_rgb: np.ndarray,
    crop_alpha: np.ndarray,
) -> np.ndarray:
    """Blur/dim/desaturate background; preserve person core pixels."""
    source = crop_rgb.astype(np.float64)
    bg = source.copy()
    bg_img = Image.fromarray(bg.astype(np.uint8), mode="RGB")
    blurred = np.array(
        bg_img.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS_PX)), dtype=np.float64
    )
    blurred = blurred * BACKGROUND_DIM_FACTOR
    blurred = _desaturate_rgb(blurred.astype(np.uint8), BACKGROUND_DESATURATION).astype(np.float64)

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
    refocused = apply_background_refocus(crop_rgb, alpha)
    return Image.fromarray(refocused, mode="RGB")


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

    return RefocusMetrics(
        subject_clipped=subject_clipped,
        retained_background_fraction=round(crop_background_fraction, 4),
        background_reduction_fraction=round(max(0.0, background_reduction), 4),
        person_mask_coverage=round(person_pixels / max(1, crop_area), 4),
        person_pixel_preservation=round(person_preservation, 4),
        edge_halo_score=round(halo_score, 4),
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
    person_mask: np.ndarray | None = None,
) -> FixtureRefocusResult:
    root = Path(repo_root).expanduser().resolve()
    source_path = resolve_fixture_source_path(fixture_id, repo_root=root)
    fixture_dir = Path(output_root) / fixture_id
    fixture_dir.mkdir(parents=True, exist_ok=True)

    if person_bbox_override is not None:
        person_bbox = load_person_bbox_override(person_bbox_override)
    else:
        localization = load_localization_json(Path(json_dir) / f"{fixture_id}.json")
        person_bbox = derive_person_bbox_from_localization(localization)

    with Image.open(source_path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size

        if person_mask is None:
            if skip_sam:
                raise ValueError("person_mask required when skip_sam=True")
            mask_path = fixture_dir / "person_mask.png"
            person_mask = segment_person_mask(
                source_path,
                person_bbox.box,
                output_path=mask_path,
                session=session,
            )
        else:
            mask_path = fixture_dir / "person_mask.png"
            save_binary_mask(person_mask, mask_path)

        crop = compute_portrait_crop(width, height, person_mask)
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

    metadata = {
        "fixture_id": fixture_id,
        "source_path": str(
            source_path.relative_to(root) if source_path.is_relative_to(root) else source_path
        ),
        "source_sha256": sha256_file(source_path),
        "person_bbox": asdict(person_bbox),
        "crop": asdict(crop),
        "metrics": asdict(metrics),
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
            "primary_aspect": "4:5",
            "fallback_aspect": "3:4",
            "crop_padding_fraction": CROP_PADDING_FRACTION,
            "blur_radius_px": BLUR_RADIUS_PX,
            "background_dim_factor": BACKGROUND_DIM_FACTOR,
            "background_desaturation": BACKGROUND_DESATURATION,
            "feather_radius_px": FEATHER_RADIUS_PX,
        },
    }
    metadata_path = fixture_dir / "metadata.json"
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
    )


def process_fixtures(
    fixture_ids: list[str],
    *,
    repo_root: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    json_dir: str | Path = DEFAULT_JSON_DIR,
    session: Sam3Session | None = None,
) -> list[FixtureRefocusResult]:
    owns_session = session is None and fixture_ids
    if owns_session:
        session = build_sam3_session()

    results: list[FixtureRefocusResult] = []
    comparison_panels: list[tuple[str, Image.Image]] = []

    for fixture_id in fixture_ids:
        result = process_fixture(
            fixture_id,
            repo_root=repo_root,
            output_root=output_root,
            json_dir=json_dir,
            session=session,
        )
        results.append(result)
        with Image.open(Path(result.metadata_path).parent / "comparison_sheet.jpg") as sheet:
            comparison_panels.append((fixture_id, sheet.copy()))

    if comparison_panels:
        combined = make_combined_comparison_sheet(comparison_panels)
        combined_path = Path(output_root) / "combined_comparison_sheet.jpg"
        combined.save(combined_path, quality=92)

    summary = {
        "fixture_ids": fixture_ids,
        "output_root": str(output_root),
        "results": [
            {
                "fixture_id": r.fixture_id,
                "crop_box": [r.crop.x0, r.crop.y0, r.crop.x1, r.crop.y1],
                "output_size": [r.crop.output_width, r.crop.output_height],
                "aspect_label": r.crop.aspect_label,
                "metrics": asdict(r.metrics),
                "recommendation": _recommend_variant(r.metrics),
            }
            for r in results
        ],
    }
    summary_path = Path(output_root) / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    return results


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
            "Bench-only selfie crop/refocus review candidates. "
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

        process_fixtures(
            fixture_ids,
            repo_root=args.repo_root,
            output_root=args.output_root,
            json_dir=args.json_dir,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
