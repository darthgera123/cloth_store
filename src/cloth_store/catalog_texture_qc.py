"""Heuristic texture/color QC comparing segmented source vs catalog output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image

from cloth_store.catalog_detail_crop import garment_mask_from_cutout

QC_HEURISTIC_NOTE = (
    "Heuristic metrics only. Source and output garment geometry differ; "
    "pixelwise comparison is invalid. Do not auto-regenerate from these scores."
)


@dataclass(frozen=True)
class TextureQCResult:
    role: str
    heuristic: bool
    note: str
    source_garment_pixel_count: int
    output_garment_pixel_count: int
    mean_delta_e: float | None
    palette_delta_e_mean: float | None
    luminance_std_ratio: float | None
    edge_density_ratio: float | None
    flags: tuple[str, ...]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "heuristic": self.heuristic,
            "note": self.note,
            "source_garment_pixel_count": self.source_garment_pixel_count,
            "output_garment_pixel_count": self.output_garment_pixel_count,
            "mean_delta_e": self.mean_delta_e,
            "palette_delta_e_mean": self.palette_delta_e_mean,
            "luminance_std_ratio": self.luminance_std_ratio,
            "edge_density_ratio": self.edge_density_ratio,
            "flags": list(self.flags),
        }


def _rgb_to_lab(pixel: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (channel / 255.0 for channel in pixel)

    def pivot(value: float) -> float:
        return ((value + 0.055) / 1.055) ** 2.4 if value > 0.04045 else value / 12.92

    r, g, b = pivot(r), pivot(g), pivot(b)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    def f(value: float) -> float:
        return value ** (1 / 3) if value > 0.008856 else (7.787 * value) + (16.0 / 116.0)

    fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
    return (116.0 * fy) - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def _delta_e(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(lab1, lab2, strict=True)) ** 0.5


def _mean_lab(pixels: list[tuple[int, int, int]]) -> tuple[float, float, float]:
    labs = [_rgb_to_lab(pixel) for pixel in pixels]
    count = len(labs)
    return (
        sum(item[0] for item in labs) / count,
        sum(item[1] for item in labs) / count,
        sum(item[2] for item in labs) / count,
    )


def _palette_centers(
    pixels: list[tuple[int, int, int]],
    *,
    clusters: int = 5,
) -> list[tuple[float, float, float]]:
    if len(pixels) <= clusters:
        return [_rgb_to_lab(pixel) for pixel in pixels]
    step = max(1, len(pixels) // clusters)
    centers = [_mean_lab(pixels[index : index + step]) for index in range(0, len(pixels), step)]
    return centers[:clusters]


def _luminance_std(pixels: list[tuple[int, int, int]]) -> float:
    values = [_rgb_to_lab(pixel)[0] for pixel in pixels]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance**0.5


def _edge_density(pixels: list[tuple[int, int, int]], width: int) -> float:
    if len(pixels) < width + 1:
        return 0.0
    gray = [sum(pixel) / 3 for pixel in pixels]
    edge_count = 0
    for index in range(len(gray) - 1):
        if abs(gray[index + 1] - gray[index]) > 8:
            edge_count += 1
    for index in range(len(gray) - width):
        if abs(gray[index + width] - gray[index]) > 8:
            edge_count += 1
    return edge_count / max(1, len(gray))


def _collect_garment_pixels(
    image: Image.Image,
    mask: list[list[bool]],
) -> list[tuple[int, int, int]]:
    rgb = image.convert("RGB")
    pixels: list[tuple[int, int, int]] = []
    for y, row in enumerate(mask):
        for x, value in enumerate(row):
            if value:
                pixels.append(rgb.getpixel((x, y)))
    return pixels


def compare_texture_heuristic(
    *,
    source_image: Image.Image,
    output_image: Image.Image,
    role: str,
) -> TextureQCResult:
    source_mask = garment_mask_from_cutout(source_image)
    output_mask = garment_mask_from_cutout(output_image)
    source_pixels = _collect_garment_pixels(source_image, source_mask)
    output_pixels = _collect_garment_pixels(output_image, output_mask)
    flags: list[str] = []

    source_count = len(source_pixels)
    output_count = len(output_pixels)
    if source_count == 0 or output_count == 0:
        return TextureQCResult(
            role=role,
            heuristic=True,
            note=QC_HEURISTIC_NOTE,
            source_garment_pixel_count=source_count,
            output_garment_pixel_count=output_count,
            mean_delta_e=None,
            palette_delta_e_mean=None,
            luminance_std_ratio=None,
            edge_density_ratio=None,
            flags=("insufficient_garment_pixels",),
        )

    mean_delta_e = _delta_e(_mean_lab(source_pixels), _mean_lab(output_pixels))
    source_palette = _palette_centers(source_pixels)
    output_palette = _palette_centers(output_pixels)
    palette_deltas = [min(_delta_e(src, out) for out in output_palette) for src in source_palette]
    palette_delta_e_mean = sum(palette_deltas) / len(palette_deltas)

    source_std = _luminance_std(source_pixels)
    output_std = _luminance_std(output_pixels)
    luminance_std_ratio = output_std / source_std if source_std > 1e-6 else None

    width = source_image.width
    source_edge = _edge_density(source_pixels, max(8, int(width**0.5)))
    output_edge = _edge_density(output_pixels, max(8, int(width**0.5)))
    edge_density_ratio = output_edge / source_edge if source_edge > 1e-6 else None

    if mean_delta_e > 25.0:
        flags.append("high_mean_color_shift")
    if palette_delta_e_mean > 30.0:
        flags.append("palette_divergence")
    if luminance_std_ratio is not None and (
        luminance_std_ratio < 0.45 or luminance_std_ratio > 2.2
    ):
        flags.append("texture_contrast_mismatch")
    if edge_density_ratio is not None and edge_density_ratio < 0.35:
        flags.append("detail_loss_suspected")

    return TextureQCResult(
        role=role,
        heuristic=True,
        note=QC_HEURISTIC_NOTE,
        source_garment_pixel_count=source_count,
        output_garment_pixel_count=output_count,
        mean_delta_e=round(mean_delta_e, 3),
        palette_delta_e_mean=round(palette_delta_e_mean, 3),
        luminance_std_ratio=round(luminance_std_ratio, 3) if luminance_std_ratio else None,
        edge_density_ratio=round(edge_density_ratio, 3) if edge_density_ratio else None,
        flags=tuple(flags),
    )
