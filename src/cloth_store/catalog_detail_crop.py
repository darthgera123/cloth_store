"""Deterministic source-derived detail crops for top garment texture reference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from cloth_store.catalog_hash import sha256_file
from cloth_store.catalog_templates import CANVAS_SIZE, WHITE_BACKGROUND

DEFAULT_DETAIL_CROP_ROOT = Path("bench/catalog_generation/detail_crops")
MIN_GARMENT_AREA_RATIO = 0.04
MIN_DETAIL_SIDE_PX = 48
MIN_GARMENT_PIXEL_RATIO = 0.70
WHITE_DISTANCE_THRESHOLD = 18.0
CENTER_WIDTH_FRAC = 0.50
CENTER_HEIGHT_FRAC = 0.40


@dataclass(frozen=True)
class DetailCropResult:
    included: bool
    output_path: Path | None
    sha256: str | None
    width: int
    height: int
    reason: str
    source_bbox: tuple[int, int, int, int] | None = None
    crop_bbox: tuple[int, int, int, int] | None = None


def _white_distance(pixel: tuple[int, int, int]) -> float:
    r, g, b = pixel
    wr, wg, wb = WHITE_BACKGROUND
    return ((r - wr) ** 2 + (g - wg) ** 2 + (b - wb) ** 2) ** 0.5


def garment_mask_from_cutout(image: Image.Image) -> list[list[bool]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    return [
        [_white_distance(rgb.getpixel((x, y))) > WHITE_DISTANCE_THRESHOLD for x in range(width)]
        for y in range(height)
    ]


def visible_garment_bbox(mask: list[list[bool]]) -> tuple[int, int, int, int] | None:
    ys = [y for y, row in enumerate(mask) if any(row)]
    xs = [x for row in mask for x, value in enumerate(row) if value]
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _luminance(pixel: tuple[int, int, int]) -> float:
    r, g, b = pixel
    return 0.299 * r + 0.587 * g + 0.114 * b


def _select_texture_crop_bbox(
    rgb: Image.Image,
    mask: list[list[bool]],
    bbox: tuple[int, int, int, int],
    *,
    canvas_size: int,
    min_side_px: int,
) -> tuple[int, int, int, int, str]:
    """Pick a garment-only subregion with stable material (low luminance variance)."""
    min_x, min_y, max_x, max_y = bbox
    bw = max_x - min_x
    bh = max_y - min_y
    crop_w = max(min_side_px, int(bw * CENTER_WIDTH_FRAC))
    crop_h = max(min_side_px, int(bh * CENTER_HEIGHT_FRAC))

    best: tuple[float, int, int] | None = None
    best_bbox: tuple[int, int, int, int] | None = None
    step = max(4, min(crop_w, crop_h) // 8)

    for top in range(min_y, max(max_y - crop_h, min_y) + 1, step):
        for left in range(min_x, max(max_x - crop_w, min_x) + 1, step):
            right = min(canvas_size, left + crop_w)
            bottom = min(canvas_size, top + crop_h)
            left = max(0, right - crop_w)
            top = max(0, bottom - crop_h)

            garment_pixels = 0
            total_pixels = (bottom - top) * (right - left)
            luminances: list[float] = []
            for y in range(top, bottom):
                row = mask[y]
                for x in range(left, right):
                    if row[x]:
                        garment_pixels += 1
                        luminances.append(_luminance(rgb.getpixel((x, y))))

            garment_ratio = garment_pixels / total_pixels if total_pixels else 0.0
            if garment_ratio < MIN_GARMENT_PIXEL_RATIO:
                continue

            variance = 0.0
            if len(luminances) > 1:
                mean_lum = sum(luminances) / len(luminances)
                variance = sum((value - mean_lum) ** 2 for value in luminances) / len(luminances)

            score = garment_ratio * 1000.0 - variance
            if best is None or score > best[0]:
                best = (score, left, top)
                best_bbox = (left, top, right, bottom)

    if best_bbox is not None:
        return (*best_bbox, "low-variance garment texture window")

    cx = (min_x + max_x) // 2
    cy = (min_y + max_y) // 2
    left = max(0, cx - crop_w // 2)
    top = max(0, cy - crop_h // 2)
    right = min(canvas_size, left + crop_w)
    bottom = min(canvas_size, top + crop_h)
    left = max(0, right - crop_w)
    top = max(0, bottom - crop_h)
    return left, top, right, bottom, "center garment detail crop fallback"


def extract_detail_crop(
    cutout_path: Path,
    *,
    output_path: Path,
    canvas_size: int = CANVAS_SIZE,
) -> DetailCropResult:
    if not cutout_path.is_file():
        return DetailCropResult(
            included=False,
            output_path=None,
            sha256=None,
            width=0,
            height=0,
            reason=f"cutout not found: {cutout_path}",
        )

    with Image.open(cutout_path) as image:
        rgb = image.convert("RGB")
        if rgb.size != (canvas_size, canvas_size):
            return DetailCropResult(
                included=False,
                output_path=None,
                sha256=None,
                width=0,
                height=0,
                reason=f"expected {canvas_size}x{canvas_size} cutout",
            )

        mask = garment_mask_from_cutout(rgb)
        garment_area = sum(1 for row in mask for value in row if value)
        if garment_area < canvas_size * canvas_size * MIN_GARMENT_AREA_RATIO:
            return DetailCropResult(
                included=False,
                output_path=None,
                sha256=None,
                width=0,
                height=0,
                reason="insufficient segmented garment area",
            )

        bbox = visible_garment_bbox(mask)
        if bbox is None:
            return DetailCropResult(
                included=False,
                output_path=None,
                sha256=None,
                width=0,
                height=0,
                reason="no garment pixels detected",
            )

        min_x, min_y, max_x, max_y = bbox
        left, top, right, bottom, selection_reason = _select_texture_crop_bbox(
            rgb,
            mask,
            bbox,
            canvas_size=canvas_size,
            min_side_px=MIN_DETAIL_SIDE_PX,
        )

        crop_mask = [row[left:right] for row in mask[top:bottom]]
        if not crop_mask:
            return DetailCropResult(
                included=False,
                output_path=None,
                sha256=None,
                width=0,
                height=0,
                reason="empty detail crop region",
                source_bbox=bbox,
            )

        garment_ratio = sum(1 for row in crop_mask for value in row if value) / (
            len(crop_mask) * len(crop_mask[0])
        )
        if garment_ratio < MIN_GARMENT_PIXEL_RATIO:
            return DetailCropResult(
                included=False,
                output_path=None,
                sha256=None,
                width=0,
                height=0,
                reason=(
                    f"detail crop garment pixel ratio {garment_ratio:.2f} "
                    f"below {MIN_GARMENT_PIXEL_RATIO:.2f}"
                ),
                source_bbox=bbox,
                crop_bbox=(left, top, right, bottom),
            )

        native_crop = rgb.crop((left, top, right, bottom))
        padded = Image.new("RGB", (canvas_size, canvas_size), WHITE_BACKGROUND)
        paste_x = (canvas_size - native_crop.width) // 2
        paste_y = (canvas_size - native_crop.height) // 2
        padded.paste(native_crop, (paste_x, paste_y))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        padded.save(output_path, format="PNG")

        digest = sha256_file(output_path)
        return DetailCropResult(
            included=True,
            output_path=output_path,
            sha256=digest,
            width=canvas_size,
            height=canvas_size,
            reason=(
                f"{selection_reason}; native resolution centered on white canvas without upscaling"
            ),
            source_bbox=bbox,
            crop_bbox=(left, top, right, bottom),
        )


def detail_crop_output_path(
    *,
    detail_root: Path,
    fixture_id: str,
    role: str,
) -> Path:
    return detail_root / f"{fixture_id}_{role}_detail.png"
