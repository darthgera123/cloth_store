"""Padded Qwen boxes -> crop-based SAM 3.1 masks for Plan 1 smoke bench.

Each role is segmented inside its padded bbox crop; masks are pasted back into
full-resolution canvases with zeros outside the crop.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from cloth_store.catalog_paths import resolve_fixture_source_path
from cloth_store.vlm_bbox import LAYOUT_DRESS, LAYOUT_SEPARATES, validate_localization

DEFAULT_PAD_FRACTION = 0.10
DEFAULT_CHECKPOINT_VERSION = "sam3.1"

ROLE_TEXT_PROMPTS: dict[str, str] = {
    "top": "top worn by the person",
    "bottom": "bottom worn by the person",
    "dress": "dress worn by the person",
}

ROLE_COLORS: dict[str, tuple[int, int, int]] = {
    "top": (255, 64, 64),
    "bottom": (64, 160, 255),
    "dress": (200, 96, 255),
}


@dataclass
class Sam3Session:
    model: Any
    processor: Any
    device: str
    autocast: Any | None = None


def load_localization_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_localization(payload)


def garment_roles(localization: dict[str, Any]) -> list[str]:
    layout = localization["layout"]
    if layout == LAYOUT_SEPARATES:
        return ["top", "bottom"]
    if layout == LAYOUT_DRESS:
        return ["dress"]
    raise ValueError(f"unsupported layout for garment roles: {layout!r}")


def pad_normalized_box(
    box: list[float],
    *,
    pad_fraction: float = DEFAULT_PAD_FRACTION,
    image_width: int,
    image_height: int,
) -> list[float]:
    """Expand a normalized xyxy box by ``pad_fraction`` of its size on each side."""
    if pad_fraction < 0:
        raise ValueError(f"pad_fraction must be non-negative, got {pad_fraction}")

    x_min, y_min, x_max, y_max = box
    px0 = x_min * image_width
    py0 = y_min * image_height
    px1 = x_max * image_width
    py1 = y_max * image_height

    pad_x = (px1 - px0) * pad_fraction
    pad_y = (py1 - py0) * pad_fraction

    px0 = max(0.0, px0 - pad_x)
    py0 = max(0.0, py0 - pad_y)
    px1 = min(float(image_width), px1 + pad_x)
    py1 = min(float(image_height), py1 + pad_y)

    return [
        px0 / image_width,
        py0 / image_height,
        px1 / image_width,
        py1 / image_height,
    ]


def normalized_xyxy_to_pixel_crop(
    box: list[float],
    *,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    """Convert normalized xyxy box to integer pixel crop bounds ``(x0, y0, x1, y1)``."""
    x_min, y_min, x_max, y_max = box
    width = (x_max - x_min) * image_width
    height = (y_max - y_min) * image_height
    if width <= 0 or height <= 0:
        raise ValueError(f"degenerate bbox after padding: {box}")

    x0 = max(0, min(image_width, int(round(x_min * image_width))))
    y0 = max(0, min(image_height, int(round(y_min * image_height))))
    x1 = max(x0 + 1, min(image_width, int(round(x_max * image_width))))
    y1 = max(y0 + 1, min(image_height, int(round(y_max * image_height))))
    return x0, y0, x1, y1


def normalized_xyxy_to_pixel_box(
    box: list[float],
    *,
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float]:
    """Convert normalized xyxy box to full-image pixel xyxy floats."""
    x_min, y_min, x_max, y_max = box
    width = (x_max - x_min) * image_width
    height = (y_max - y_min) * image_height
    if width <= 0 or height <= 0:
        raise ValueError(f"degenerate bbox: {box}")
    return (
        x_min * image_width,
        y_min * image_height,
        x_max * image_width,
        y_max * image_height,
    )


def original_box_to_crop_prompt(
    original_box: list[float],
    crop_bounds: tuple[int, int, int, int],
    *,
    image_width: int,
    image_height: int,
) -> list[float]:
    """Transform an unpadded Qwen bbox into crop-relative SAM pixel xyxy."""
    x0, y0, x1, y1 = crop_bounds
    crop_w = x1 - x0
    crop_h = y1 - y0
    ox0, oy0, ox1, oy1 = normalized_xyxy_to_pixel_box(
        original_box,
        image_width=image_width,
        image_height=image_height,
    )
    rel_x0 = max(0.0, min(float(crop_w), ox0 - x0))
    rel_y0 = max(0.0, min(float(crop_h), oy0 - y0))
    rel_x1 = max(rel_x0 + 1.0, min(float(crop_w), ox1 - x0))
    rel_y1 = max(rel_y0 + 1.0, min(float(crop_h), oy1 - y0))
    if rel_x1 <= rel_x0 or rel_y1 <= rel_y0:
        raise ValueError(f"degenerate crop-relative box for {original_box} in crop {crop_bounds}")
    return [rel_x0, rel_y0, rel_x1, rel_y1]


def pixel_xyxy_to_normalized_cxcywh(
    box: list[float],
    *,
    image_width: int,
    image_height: int,
) -> list[float]:
    x0, y0, x1, y1 = box
    cx = ((x0 + x1) / 2.0) / image_width
    cy = ((y0 + y1) / 2.0) / image_height
    width = (x1 - x0) / image_width
    height = (y1 - y0) / image_height
    return [cx, cy, width, height]


def place_crop_mask_in_full_image(
    crop_mask: np.ndarray,
    crop_bounds: tuple[int, int, int, int],
    *,
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """Paste a crop-local binary mask into a zeroed full-resolution canvas."""
    x0, y0, x1, y1 = crop_bounds
    crop_h = y1 - y0
    crop_w = x1 - x0
    if crop_mask.shape != (crop_h, crop_w):
        raise ValueError(
            f"crop mask shape {crop_mask.shape} does not match crop bounds "
            f"{crop_bounds} ({crop_w}x{crop_h})"
        )

    full_mask = np.zeros((image_height, image_width), dtype=bool)
    full_mask[y0:y1, x0:x1] = crop_mask.astype(bool)
    return full_mask


def masks_to_numpy(masks: Any) -> np.ndarray:
    if hasattr(masks, "detach"):
        masks = masks.detach().float().cpu().numpy()
    array = np.asarray(masks)
    if array.dtype != bool:
        array = array > 0.5
    return array


def select_role_mask(masks: Any, scores: Any, *, role: str) -> np.ndarray:
    mask_array = masks_to_numpy(masks)
    if mask_array.size == 0:
        raise RuntimeError(f"SAM returned no masks for role {role!r}")

    if mask_array.ndim == 4:
        mask_array = mask_array.squeeze(1)

    score_array = np.asarray(
        scores.detach().float().cpu().numpy() if hasattr(scores, "detach") else scores
    )
    best_index = int(score_array.argmax()) if score_array.size else 0
    return mask_array[best_index].astype(bool)


def save_binary_mask(mask: np.ndarray, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(output_path)


def render_mask_overlay(
    image: Image.Image,
    masks_by_role: dict[str, np.ndarray],
    *,
    alpha: float = 0.45,
) -> Image.Image:
    base = np.array(image.convert("RGB"), dtype=np.float32)
    overlay = base.copy()

    for role, mask in masks_by_role.items():
        color = np.array(ROLE_COLORS.get(role, (255, 255, 255)), dtype=np.float32)
        role_pixels = mask.astype(bool)
        overlay[role_pixels] = overlay[role_pixels] * (1.0 - alpha) + color * alpha

    return Image.fromarray(overlay.astype(np.uint8))


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def make_contact_sheet(
    panels: list[tuple[str, Image.Image]],
    *,
    font: ImageFont.ImageFont | None = None,
) -> Image.Image:
    label_font = font or load_font(28)
    cols, rows = 3, 2
    thumb_w, thumb_h = 480, 640
    header_h = 36
    margin = 12
    sheet_w = cols * thumb_w + (cols + 1) * margin
    sheet_h = rows * (thumb_h + header_h) + (rows + 1) * margin
    sheet = Image.new("RGB", (sheet_w, sheet_h), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)

    for index, (fixture_id, panel) in enumerate(panels):
        col = index % cols
        row = index // cols
        x = margin + col * (thumb_w + margin)
        y = margin + row * (thumb_h + header_h + margin)
        draw.text((x, y), fixture_id, fill=(240, 240, 240), font=label_font)
        resized = panel.copy()
        resized.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        paste_x = x + (thumb_w - resized.width) // 2
        paste_y = y + header_h + (thumb_h - resized.height) // 2
        sheet.paste(resized, (paste_x, paste_y))

    return sheet


def role_output_paths(output_dir: Path, role: str) -> Path:
    return output_dir / f"{role}.png"


def overlay_output_path(output_dir: Path) -> Path:
    return output_dir / "overlay.jpg"


def build_sam3_session(*, checkpoint_version: str = DEFAULT_CHECKPOINT_VERSION) -> Sam3Session:
    import contextlib

    import torch
    from sam3.model.sam3_image_processor import Sam3Processor
    from sam3.model_builder import build_sam3_image_model, download_ckpt_from_hf

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    checkpoint_path = download_ckpt_from_hf(version=checkpoint_version)
    model = build_sam3_image_model(
        checkpoint_path=checkpoint_path,
        load_from_HF=False,
        enable_inst_interactivity=False,
        device=device,
    )
    processor = Sam3Processor(model, device=device)
    autocast = (
        torch.autocast("cuda", dtype=torch.bfloat16)
        if device == "cuda"
        else contextlib.nullcontext()
    )
    if device == "cuda":
        autocast.__enter__()
    return Sam3Session(model=model, processor=processor, device=device, autocast=autocast)


def predict_role_mask(
    session: Sam3Session,
    image: Image.Image,
    pixel_box: list[float],
    *,
    role: str,
) -> np.ndarray:
    crop_w, crop_h = image.size
    state = session.processor.set_image(image)
    state = session.processor.set_text_prompt(
        prompt=ROLE_TEXT_PROMPTS[role],
        state=state,
    )
    norm_box = pixel_xyxy_to_normalized_cxcywh(
        pixel_box,
        image_width=crop_w,
        image_height=crop_h,
    )
    state = session.processor.add_geometric_prompt(
        box=norm_box,
        label=True,
        state=state,
    )
    masks = state["masks"]
    scores = state["scores"]
    return select_role_mask(masks, scores, role=role)


def segment_garment_roles(
    image_path: str | Path,
    localization: dict[str, Any],
    *,
    output_dir: str | Path,
    pad_fraction: float = DEFAULT_PAD_FRACTION,
    session: Sam3Session | None = None,
    checkpoint_version: str = DEFAULT_CHECKPOINT_VERSION,
) -> dict[str, np.ndarray]:
    if session is None:
        session = build_sam3_session(checkpoint_version=checkpoint_version)

    resolved_image = Path(image_path).expanduser().resolve()
    if not resolved_image.is_file():
        raise FileNotFoundError(f"image not found: {resolved_image}")

    resolved_output = Path(output_dir)
    resolved_output.mkdir(parents=True, exist_ok=True)

    with Image.open(resolved_image) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        masks_by_role: dict[str, np.ndarray] = {}

        for role in garment_roles(localization):
            original_box = localization[role]
            padded_box = pad_normalized_box(
                original_box,
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
                original_box,
                crop_bounds,
                image_width=width,
                image_height=height,
            )
            crop_mask = predict_role_mask(
                session,
                crop,
                prompt_box,
                role=role,
            )
            mask = place_crop_mask_in_full_image(
                crop_mask,
                crop_bounds,
                image_width=width,
                image_height=height,
            )
            masks_by_role[role] = mask
            save_binary_mask(mask, role_output_paths(resolved_output, role))

        overlay = render_mask_overlay(rgb, masks_by_role)
        overlay.save(overlay_output_path(resolved_output), quality=92)

    return masks_by_role


def segment_fixtures(
    *,
    repo_root: str | Path,
    json_dir: str | Path,
    output_root: str | Path,
    fixture_ids: list[str],
    pad_fraction: float = DEFAULT_PAD_FRACTION,
    checkpoint_version: str = DEFAULT_CHECKPOINT_VERSION,
) -> list[tuple[str, Image.Image]]:
    root = Path(repo_root)
    session = build_sam3_session(checkpoint_version=checkpoint_version)
    panels: list[tuple[str, Image.Image]] = []

    for fixture_id in fixture_ids:
        image_path = resolve_fixture_source_path(fixture_id, repo_root=root)
        json_path = Path(json_dir) / f"{fixture_id}.json"
        fixture_output = Path(output_root) / fixture_id
        localization = load_localization_json(json_path)
        segment_garment_roles(
            image_path,
            localization,
            output_dir=fixture_output,
            pad_fraction=pad_fraction,
            session=session,
        )
        with Image.open(fixture_output / "overlay.jpg") as overlay:
            panels.append((fixture_id, overlay.copy()))

    contact_path = Path(output_root) / "contact_sheet.jpg"
    make_contact_sheet(panels).save(contact_path, quality=92)
    return panels


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Segment garment roles inside padded Qwen bbox crops with official "
            f"SAM 3.1 ({DEFAULT_CHECKPOINT_VERSION}, facebook/sam3.1)."
        )
    )
    parser.add_argument("image", nargs="?", help="Path to a mirror-selfie image.")
    parser.add_argument(
        "localization_json",
        nargs="?",
        help="Path to validated bbox JSON.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="Directory for role PNG masks and overlay.jpg.",
    )
    parser.add_argument(
        "--pad-fraction",
        type=float,
        default=DEFAULT_PAD_FRACTION,
        help="Fraction of bbox width/height to pad on each side (default: 0.10).",
    )
    parser.add_argument(
        "--checkpoint-version",
        default=DEFAULT_CHECKPOINT_VERSION,
        help=f"SAM checkpoint version (default: {DEFAULT_CHECKPOINT_VERSION}).",
    )
    parser.add_argument(
        "--batch-fixtures",
        nargs="+",
        help="Run multiple fixtures: ids like outfit_1 with --repo-root and --json-dir.",
    )
    parser.add_argument(
        "--repo-root",
        help="Repo root containing outfit_*.jpeg (required with --batch-fixtures).",
    )
    parser.add_argument(
        "--json-dir",
        help="Directory containing outfit_*.json (required with --batch-fixtures).",
    )
    args = parser.parse_args()

    try:
        if args.batch_fixtures:
            if not args.repo_root or not args.json_dir:
                raise ValueError("--batch-fixtures requires --repo-root and --json-dir")
            segment_fixtures(
                repo_root=args.repo_root,
                json_dir=args.json_dir,
                output_root=args.output_dir,
                fixture_ids=args.batch_fixtures,
                pad_fraction=args.pad_fraction,
                checkpoint_version=args.checkpoint_version,
            )
            return

        if not args.localization_json:
            raise ValueError("localization_json is required unless --batch-fixtures is set")

        localization = load_localization_json(args.localization_json)
        segment_garment_roles(
            args.image,
            localization,
            output_dir=args.output_dir,
            pad_fraction=args.pad_fraction,
            checkpoint_version=args.checkpoint_version,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
