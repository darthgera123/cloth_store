"""Deterministic SAM mask -> normalized 512x512 catalog cutouts for Plan 1."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from cloth_store.catalog_paths import resolve_fixture_source_path
from cloth_store.sam_masks import garment_roles, load_font, load_localization_json
from cloth_store.vlm_bbox import LAYOUT_DRESS

CANVAS_SIZE = 512
MARGIN_FRACTION = 0.09
WHITE_BACKGROUND = (255, 255, 255)

CATALOG_ROLE_NAMES: dict[str, str] = {
    "top": "catalog_top.png",
    "bottom": "catalog_bottom.png",
    "dress": "catalog_dress.png",
}


def mask_to_bool_array(mask: Image.Image | np.ndarray) -> np.ndarray:
    array = np.array(mask.convert("L")) if isinstance(mask, Image.Image) else np.asarray(mask)
    return array > 0


def empty_mask_error(role: str) -> ValueError:
    return ValueError(f"empty mask for role {role!r}: no foreground pixels")


def foreground_bounds(mask: np.ndarray) -> tuple[int, int, int, int]:
    """Return xyxy pixel bounds spanning all nonzero mask pixels."""
    ys, xs = np.where(mask)
    if ys.size == 0:
        raise empty_mask_error("unknown")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def expand_bounds(
    bounds: tuple[int, int, int, int],
    *,
    margin_fraction: float,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bounds
    crop_w = max(1, x1 - x0)
    crop_h = max(1, y1 - y0)
    pad_x = int(round(crop_w * margin_fraction))
    pad_y = int(round(crop_h * margin_fraction))
    return (
        max(0, x0 - pad_x),
        max(0, y0 - pad_y),
        min(image_width, x1 + pad_x),
        min(image_height, y1 + pad_y),
    )


def masked_rgb_cutout(image_rgb: Image.Image, mask: np.ndarray) -> Image.Image:
    rgb = np.array(image_rgb.convert("RGB"))
    white = np.full_like(rgb, 255)
    combined = np.where(mask[..., None], rgb, white)
    return Image.fromarray(combined.astype(np.uint8), mode="RGB")


def fit_and_center_on_canvas(
    cutout: Image.Image,
    *,
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
) -> Image.Image:
    fitted = cutout.copy()
    max_side = max(1, int(round(canvas_size * (1.0 - 2.0 * margin_fraction))))
    fitted.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (canvas_size, canvas_size), WHITE_BACKGROUND)
    paste_x = (canvas_size - fitted.width) // 2
    paste_y = (canvas_size - fitted.height) // 2
    canvas.paste(fitted, (paste_x, paste_y))
    return canvas


def fit_mask_on_canvas(
    mask: np.ndarray,
    *,
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
) -> np.ndarray:
    """Fit a cropped boolean mask onto the same 512x512 canvas as catalog cutouts."""
    mask_image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    max_side = max(1, int(round(canvas_size * (1.0 - 2.0 * margin_fraction))))
    fitted = mask_image.copy()
    fitted.thumbnail((max_side, max_side), Image.Resampling.NEAREST)

    canvas = np.zeros((canvas_size, canvas_size), dtype=bool)
    paste_x = (canvas_size - fitted.width) // 2
    paste_y = (canvas_size - fitted.height) // 2
    fitted_bool = np.array(fitted) > 0
    canvas[paste_y : paste_y + fitted.height, paste_x : paste_x + fitted.width] = fitted_bool
    return canvas


def sam_mask_on_cutout_canvas(
    image_rgb: Image.Image,
    mask: np.ndarray,
    *,
    role: str = "unknown",
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
) -> np.ndarray:
    """Project a full-resolution SAM mask onto the catalog cutout canvas."""
    if not mask.any():
        raise empty_mask_error(role)

    width, height = image_rgb.size
    bounds = foreground_bounds(mask)
    crop_bounds = expand_bounds(
        bounds,
        margin_fraction=margin_fraction,
        image_width=width,
        image_height=height,
    )
    x0, y0, x1, y1 = crop_bounds
    cropped_mask = mask[y0:y1, x0:x1]
    return fit_mask_on_canvas(
        cropped_mask,
        canvas_size=canvas_size,
        margin_fraction=margin_fraction,
    )


def catalog_output_path(output_dir: Path, role: str) -> Path:
    filename = CATALOG_ROLE_NAMES.get(role)
    if filename is None:
        raise ValueError(f"unsupported catalog role: {role!r}")
    return output_dir / filename


def generate_fixture_cutouts(
    image_path: str | Path,
    localization: dict[str, Any],
    *,
    mask_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Image.Image]:
    resolved_image = Path(image_path).expanduser().resolve()
    resolved_masks = Path(mask_dir)
    resolved_output = Path(output_dir)
    resolved_output.mkdir(parents=True, exist_ok=True)

    cutouts: dict[str, Image.Image] = {}
    with Image.open(resolved_image) as image:
        rgb = image.convert("RGB")
        for role in garment_roles(localization):
            mask_path = resolved_masks / f"{role}.png"
            if not mask_path.is_file():
                raise FileNotFoundError(f"mask not found: {mask_path}")
            with Image.open(mask_path) as mask_image:
                mask = mask_to_bool_array(mask_image)
            if mask.shape[:2] != (rgb.height, rgb.width):
                raise ValueError(
                    f"mask shape {mask.shape[:2]} does not match image size "
                    f"{rgb.width}x{rgb.height} for role {role!r}"
                )
            cutout = render_catalog_cutout(rgb, mask, role=role)
            output_path = catalog_output_path(resolved_output, role)
            cutout.save(output_path)
            cutouts[role] = cutout

        if localization["layout"] == LAYOUT_DRESS and "dress" in cutouts:
            cutouts["dress"].save(catalog_output_path(resolved_output, "dress"))

    return cutouts


def render_catalog_cutout(
    image_rgb: Image.Image,
    mask: np.ndarray,
    *,
    role: str = "unknown",
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
) -> Image.Image:
    if not mask.any():
        raise empty_mask_error(role)

    width, height = image_rgb.size
    bounds = foreground_bounds(mask)
    crop_bounds = expand_bounds(
        bounds,
        margin_fraction=margin_fraction,
        image_width=width,
        image_height=height,
    )
    x0, y0, x1, y1 = crop_bounds
    cropped_rgb = image_rgb.crop((x0, y0, x1, y1))
    cropped_mask = mask[y0:y1, x0:x1]
    rgb_cutout = masked_rgb_cutout(cropped_rgb, cropped_mask)
    return fit_and_center_on_canvas(
        rgb_cutout,
        canvas_size=canvas_size,
        margin_fraction=margin_fraction,
    )


def make_catalog_contact_sheet(
    panels: list[tuple[str, str, Image.Image]],
    *,
    thumb_size: int = 220,
    font: ImageFont.ImageFont | None = None,
) -> Image.Image:
    label_font = font or load_font(22)
    cols = 3
    rows = max(1, (len(panels) + cols - 1) // cols)
    header_h = 28
    margin = 10
    cell_w = thumb_size + 2 * margin
    cell_h = thumb_size + header_h + 2 * margin
    sheet_w = cols * cell_w + margin
    sheet_h = rows * cell_h + margin
    sheet = Image.new("RGB", (sheet_w, sheet_h), WHITE_BACKGROUND)
    draw = ImageDraw.Draw(sheet)

    for index, (fixture_id, role, cutout) in enumerate(panels):
        col = index % cols
        row = index // cols
        x = margin + col * cell_w
        y = margin + row * cell_h
        label = f"{fixture_id} / {role}"
        draw.text((x + margin, y), label, fill=(20, 20, 20), font=label_font)

        preview = cutout.copy()
        preview.thumbnail((thumb_size, thumb_size), Image.Resampling.LANCZOS)
        paste_x = x + margin + (thumb_size - preview.width) // 2
        paste_y = y + header_h + margin + (thumb_size - preview.height) // 2
        sheet.paste(preview, (paste_x, paste_y))

    return sheet


def generate_fixtures(
    *,
    repo_root: str | Path,
    json_dir: str | Path,
    mask_root: str | Path,
    output_root: str | Path,
    fixture_ids: list[str],
) -> list[tuple[str, str, Image.Image]]:
    root = Path(repo_root)
    panels: list[tuple[str, str, Image.Image]] = []

    for fixture_id in fixture_ids:
        image_path = resolve_fixture_source_path(fixture_id, repo_root=root)
        json_path = Path(json_dir) / f"{fixture_id}.json"
        mask_dir = Path(mask_root) / fixture_id
        fixture_output = Path(output_root) / fixture_id
        localization = load_localization_json(json_path)
        cutouts = generate_fixture_cutouts(
            image_path,
            localization,
            mask_dir=mask_dir,
            output_dir=fixture_output,
        )
        for role, cutout in cutouts.items():
            panels.append((fixture_id, role, cutout))

    contact_path = Path(output_root) / "contact_sheet.jpg"
    make_catalog_contact_sheet(panels).save(contact_path, quality=92)
    return panels


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render normalized 512x512 catalog cutouts from SAM role masks."
    )
    parser.add_argument("image", nargs="?", help="Path to a mirror-selfie image.")
    parser.add_argument(
        "localization_json",
        nargs="?",
        help="Path to validated bbox JSON.",
    )
    parser.add_argument(
        "--mask-dir",
        help="Directory containing role PNG masks (top.png, bottom.png, ...).",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="Directory for catalog_*.png cutouts.",
    )
    parser.add_argument(
        "--batch-fixtures",
        nargs="+",
        help="Run multiple fixtures with --repo-root, --json-dir, and --mask-root.",
    )
    parser.add_argument(
        "--repo-root",
        help="Repo root containing outfit_*.jpeg (required with --batch-fixtures).",
    )
    parser.add_argument(
        "--json-dir",
        help="Directory containing outfit_*.json (required with --batch-fixtures).",
    )
    parser.add_argument(
        "--mask-root",
        help="Root directory containing outfit_*/ role masks (required with --batch-fixtures).",
    )
    args = parser.parse_args()

    try:
        if args.batch_fixtures:
            if not args.repo_root or not args.json_dir or not args.mask_root:
                raise ValueError(
                    "--batch-fixtures requires --repo-root, --json-dir, and --mask-root"
                )
            generate_fixtures(
                repo_root=args.repo_root,
                json_dir=args.json_dir,
                mask_root=args.mask_root,
                output_root=args.output_dir,
                fixture_ids=args.batch_fixtures,
            )
            return

        if not args.image or not args.localization_json or not args.mask_dir:
            raise ValueError(
                "image, localization_json, and --mask-dir are required unless "
                "--batch-fixtures is set"
            )

        localization = load_localization_json(args.localization_json)
        generate_fixture_cutouts(
            args.image,
            localization,
            mask_dir=args.mask_dir,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
