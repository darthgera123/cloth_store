"""Deterministic canonical garment template silhouettes for catalog benchmarks.

Templates are neutral front-facing geometry/layout targets (not photorealistic
garments). SVG sources and 512x512 RGB PNGs share the same polygon definitions.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

# Plan 1 canvas size; templates use a tighter margin for larger silhouettes.
CANVAS_SIZE = 512
MARGIN_FRACTION = 0.04
WHITE_BACKGROUND = (255, 255, 255)

# Neutral flat fill — no texture, branding, or fashion detail.
SILHOUETTE_FILL = (90, 90, 90)

# Normalized design-space scale before bbox centering.
DESIGN_WIDTH = 320
DESIGN_HEIGHT = 420


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    display_name: str
    role: str
    sleeve: str | None
    top_kind: str | None
    bottom_kind: str | None
    polygons: tuple[tuple[tuple[float, float], ...], ...]
    cutouts: tuple[tuple[tuple[float, float], ...], ...] = ()

    def to_manifest_entry(self, repo_relative_png: str, repo_relative_svg: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "role": self.role,
            "sleeve": self.sleeve,
            "top_kind": self.top_kind,
            "bottom_kind": self.bottom_kind,
            "png": repo_relative_png,
            "svg": repo_relative_svg,
        }


def _torso_polygon() -> tuple[tuple[float, float], ...]:
    """Shared front-facing torso block (crew neck, straight sides, flat hem)."""
    return (
        (0.36, 0.06),
        (0.42, 0.04),
        (0.50, 0.03),
        (0.58, 0.04),
        (0.64, 0.06),
        (0.70, 0.12),
        (0.72, 0.24),
        (0.70, 0.48),
        (0.68, 0.56),
        (0.32, 0.56),
        (0.30, 0.48),
        (0.28, 0.24),
        (0.30, 0.12),
    )


def _full_sleeve_left() -> tuple[tuple[float, float], ...]:
    return (
        (0.30, 0.12),
        (0.22, 0.14),
        (0.14, 0.22),
        (0.08, 0.34),
        (0.06, 0.46),
        (0.08, 0.50),
        (0.14, 0.50),
        (0.18, 0.44),
        (0.22, 0.30),
        (0.28, 0.24),
    )


def _full_sleeve_right() -> tuple[tuple[float, float], ...]:
    return tuple((1.0 - x, y) for x, y in reversed(_full_sleeve_left()))


def _half_sleeve_left() -> tuple[tuple[float, float], ...]:
    return (
        (0.30, 0.12),
        (0.24, 0.14),
        (0.18, 0.20),
        (0.14, 0.28),
        (0.16, 0.32),
        (0.22, 0.30),
        (0.28, 0.24),
    )


def _half_sleeve_right() -> tuple[tuple[float, float], ...]:
    return tuple((1.0 - x, y) for x, y in reversed(_half_sleeve_left()))


def _skirt_polygon() -> tuple[tuple[float, float], ...]:
    return (
        (0.38, 0.08),
        (0.62, 0.08),
        (0.66, 0.12),
        (0.74, 0.28),
        (0.78, 0.52),
        (0.80, 0.78),
        (0.76, 0.82),
        (0.24, 0.82),
        (0.20, 0.78),
        (0.22, 0.52),
        (0.26, 0.28),
        (0.34, 0.12),
    )


def _skirt_knee_length_polygon() -> tuple[tuple[float, float], ...]:
    """Knee-length skirt: A-line silhouette with hem ending around knee (~55% canvas height)."""
    return (
        (0.38, 0.08),
        (0.62, 0.08),
        (0.66, 0.12),
        (0.72, 0.24),
        (0.74, 0.38),
        (0.72, 0.52),
        (0.59, 0.56),
        (0.41, 0.56),
        (0.39, 0.52),
        (0.37, 0.38),
        (0.39, 0.24),
        (0.38, 0.12),
    )


def _skirt_long_polygon() -> tuple[tuple[float, float], ...]:
    """Long/maxi skirt: A-line silhouette extended to ankle/floor length (~92% canvas height)."""
    return (
        (0.38, 0.08),
        (0.62, 0.08),
        (0.66, 0.12),
        (0.74, 0.28),
        (0.78, 0.52),
        (0.82, 0.78),
        (0.84, 0.90),
        (0.80, 0.92),
        (0.20, 0.92),
        (0.16, 0.90),
        (0.18, 0.78),
        (0.22, 0.52),
        (0.26, 0.28),
        (0.34, 0.12),
    )


def _skirt_pencil_polygon() -> tuple[tuple[float, float], ...]:
    """Straight/pencil skirt: fitted waist, nearly parallel sides, minimal hem flare.

    Target rendered proportions on 512×512 canvas (after margin centering):
    waist ~34%, hip/body ~47%, hem ~43%, hem/waist ~1.25. Wider than v1 narrow
    pencil (~13% waist) but less flared than A-line skirt (~51% hip, ~55% hem).
    """
    return (
        (0.34, 0.08),
        (0.66, 0.08),
        (0.68, 0.12),
        (0.73, 0.28),
        (0.76, 0.50),
        (0.75, 0.72),
        (0.71, 0.82),
        (0.29, 0.82),
        (0.26, 0.72),
        (0.25, 0.50),
        (0.27, 0.28),
        (0.32, 0.12),
    )


def _pants_waist_band() -> tuple[tuple[float, float], ...]:
    """Narrow waist band; legs begin separately below y=0.10."""
    return (
        (0.34, 0.08),
        (0.66, 0.08),
        (0.66, 0.12),
        (0.34, 0.12),
    )


def _pants_left_leg() -> tuple[tuple[float, float], ...]:
    """Left leg with inner separation from y=0.10 (legacy split-leg silhouette)."""
    return (
        (0.34, 0.10),
        (0.48, 0.10),
        (0.49, 0.34),
        (0.46, 0.56),
        (0.44, 0.82),
        (0.42, 0.88),
        (0.30, 0.88),
        (0.28, 0.82),
        (0.26, 0.56),
        (0.28, 0.34),
    )


def _pants_right_leg() -> tuple[tuple[float, float], ...]:
    return tuple((1.0 - x, y) for x, y in reversed(_pants_left_leg()))


def _dress_knee_half_sleeve_body() -> tuple[tuple[float, float], ...]:
    """One-piece dress body from neckline to knee-length hem without waist separation."""
    return (
        (0.36, 0.06),
        (0.42, 0.04),
        (0.50, 0.03),
        (0.58, 0.04),
        (0.64, 0.06),
        (0.70, 0.12),
        (0.72, 0.24),
        (0.70, 0.48),
        (0.74, 0.52),
        (0.72, 0.56),
        (0.59, 0.58),
        (0.41, 0.58),
        (0.39, 0.56),
        (0.37, 0.52),
        (0.30, 0.48),
        (0.28, 0.24),
        (0.30, 0.12),
    )


def _blazer_body() -> tuple[tuple[float, float], ...]:
    """Structured jacket body: wide squared shoulders, straight sides, hip-length hem."""
    return (
        (0.18, 0.10),
        (0.24, 0.07),
        (0.34, 0.05),
        (0.50, 0.04),
        (0.66, 0.05),
        (0.76, 0.07),
        (0.82, 0.10),
        (0.84, 0.18),
        (0.82, 0.34),
        (0.80, 0.58),
        (0.78, 0.64),
        (0.22, 0.64),
        (0.20, 0.58),
        (0.18, 0.34),
        (0.16, 0.18),
    )


def _blazer_sleeve_left() -> tuple[tuple[float, float], ...]:
    return (
        (0.16, 0.18),
        (0.10, 0.20),
        (0.04, 0.28),
        (0.02, 0.40),
        (0.02, 0.52),
        (0.04, 0.56),
        (0.10, 0.56),
        (0.14, 0.50),
        (0.16, 0.38),
        (0.18, 0.34),
    )


def _blazer_sleeve_right() -> tuple[tuple[float, float], ...]:
    return tuple((1.0 - x, y) for x, y in reversed(_blazer_sleeve_left()))


def _blazer_lapel_left() -> tuple[tuple[float, float], ...]:
    return (
        (0.34, 0.05),
        (0.40, 0.06),
        (0.46, 0.14),
        (0.48, 0.24),
        (0.44, 0.26),
        (0.38, 0.18),
        (0.34, 0.10),
    )


def _blazer_lapel_right() -> tuple[tuple[float, float], ...]:
    return tuple((1.0 - x, y) for x, y in reversed(_blazer_lapel_left()))


def _blazer_front_opening() -> tuple[tuple[float, float], ...]:
    """Open-front V and center gap (rendered as white cutouts over the body)."""
    return (
        (0.46, 0.06),
        (0.50, 0.05),
        (0.54, 0.06),
        (0.52, 0.18),
        (0.50, 0.52),
        (0.48, 0.18),
    )


def _armhole_cutout_left() -> tuple[tuple[float, float], ...]:
    """Scooped armhole cutout for sleeveless tops (white gap in shoulder region)."""
    return (
        (0.28, 0.11),
        (0.33, 0.09),
        (0.35, 0.16),
        (0.33, 0.22),
        (0.29, 0.20),
    )


def _armhole_cutout_right() -> tuple[tuple[float, float], ...]:
    return tuple((1.0 - x, y) for x, y in reversed(_armhole_cutout_left()))


def _waistcoat_body() -> tuple[tuple[float, float], ...]:
    """Sleeveless waistcoat body: structured shoulders, armholes, hip-length closed front."""
    return (
        (0.22, 0.12),
        (0.28, 0.08),
        (0.34, 0.06),
        (0.38, 0.10),
        (0.40, 0.06),
        (0.44, 0.04),
        (0.50, 0.03),
        (0.56, 0.04),
        (0.60, 0.06),
        (0.62, 0.10),
        (0.66, 0.06),
        (0.72, 0.08),
        (0.78, 0.12),
        (0.80, 0.22),
        (0.78, 0.48),
        (0.76, 0.62),
        (0.24, 0.62),
        (0.22, 0.48),
        (0.20, 0.22),
    )


TEMPLATE_SPECS: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        id="top_full_sleeve",
        display_name="Full / long-sleeve top",
        role="top",
        sleeve="full",
        top_kind="generic",
        bottom_kind=None,
        polygons=(_torso_polygon(), _full_sleeve_left(), _full_sleeve_right()),
    ),
    TemplateSpec(
        id="top_half_sleeve",
        display_name="Half / short-sleeve top",
        role="top",
        sleeve="half",
        top_kind="generic",
        bottom_kind=None,
        polygons=(_torso_polygon(), _half_sleeve_left(), _half_sleeve_right()),
    ),
    TemplateSpec(
        id="top_sleeveless",
        display_name="Sleeveless blouse / top",
        role="top",
        sleeve="sleeveless",
        top_kind="generic",
        bottom_kind=None,
        polygons=(_torso_polygon(),),
        cutouts=(_armhole_cutout_left(), _armhole_cutout_right()),
    ),
    TemplateSpec(
        id="blazer",
        display_name="Blazer / suit jacket",
        role="top",
        sleeve="full",
        top_kind="blazer",
        bottom_kind=None,
        polygons=(
            _blazer_body(),
            _blazer_sleeve_left(),
            _blazer_sleeve_right(),
            _blazer_lapel_left(),
            _blazer_lapel_right(),
        ),
        cutouts=(_blazer_front_opening(),),
    ),
    TemplateSpec(
        id="waistcoat_closed",
        display_name="Closed waistcoat / vest",
        role="top",
        sleeve=None,
        top_kind="waistcoat",
        bottom_kind=None,
        polygons=(
            _waistcoat_body(),
            _blazer_lapel_left(),
            _blazer_lapel_right(),
        ),
    ),
    TemplateSpec(
        id="dress_knee_length_half_sleeve",
        display_name="Knee-length half-sleeve dress",
        role="dress",
        sleeve="half",
        top_kind="dress",
        bottom_kind=None,
        polygons=(
            _dress_knee_half_sleeve_body(),
            _half_sleeve_left(),
            _half_sleeve_right(),
        ),
    ),
    TemplateSpec(
        id="dress_knee_length_full_sleeve",
        display_name="Knee-length full-sleeve dress",
        role="dress",
        sleeve="full",
        top_kind="dress",
        bottom_kind=None,
        polygons=(
            _dress_knee_half_sleeve_body(),
            _full_sleeve_left(),
            _full_sleeve_right(),
        ),
    ),
    TemplateSpec(
        id="skirt",
        display_name="Skirt",
        role="bottom",
        sleeve=None,
        top_kind=None,
        bottom_kind="skirt",
        polygons=(_skirt_polygon(),),
    ),
    TemplateSpec(
        id="skirt_pencil",
        display_name="Pencil / straight skirt",
        role="bottom",
        sleeve=None,
        top_kind=None,
        bottom_kind="skirt_pencil",
        polygons=(_skirt_pencil_polygon(),),
    ),
    TemplateSpec(
        id="skirt_knee_length",
        display_name="Knee-length skirt",
        role="bottom",
        sleeve=None,
        top_kind=None,
        bottom_kind="skirt_knee_length",
        polygons=(_skirt_knee_length_polygon(),),
    ),
    TemplateSpec(
        id="skirt_long",
        display_name="Long / maxi skirt",
        role="bottom",
        sleeve=None,
        top_kind=None,
        bottom_kind="skirt_long",
        polygons=(_skirt_long_polygon(),),
    ),
    TemplateSpec(
        id="pants",
        display_name="Pants / trousers",
        role="bottom",
        sleeve=None,
        top_kind=None,
        bottom_kind="pants",
        polygons=(_pants_waist_band(), _pants_left_leg(), _pants_right_leg()),
    ),
)

TEMPLATE_BY_ID: dict[str, TemplateSpec] = {spec.id: spec for spec in TEMPLATE_SPECS}


def visible_foreground_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    """Return xyxy bounds of non-white visible pixels."""
    if image.size != (CANVAS_SIZE, CANVAS_SIZE):
        raise ValueError(f"expected {CANVAS_SIZE}x{CANVAS_SIZE} image, got {image.size}")
    pixels = image.load()
    min_x = min_y = CANVAS_SIZE
    max_x = max_y = -1
    for y in range(CANVAS_SIZE):
        for x in range(CANVAS_SIZE):
            if pixels[x, y] != WHITE_BACKGROUND:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
    if max_x < min_x:
        raise ValueError("image has no visible foreground pixels")
    return min_x, min_y, max_x, max_y


def pants_centerline_gap_rows(image: Image.Image) -> int:
    """Count center-column white rows in the top 30% of the silhouette (waist/hip band)."""
    min_x, min_y, max_x, max_y = visible_foreground_bounds(image)
    mid = CANVAS_SIZE // 2
    torso_end = min_y + max(1, int((max_y - min_y) * 0.30))
    gap_rows = 0
    for y in range(min_y, torso_end):
        if image.getpixel((mid, y)) == WHITE_BACKGROUND:
            gap_rows += 1
    return gap_rows


def template_silhouette_width_metrics(image: Image.Image) -> dict[str, float]:
    """Return waist/mid/hem widths as fractions of canvas width (512=1.0 scale uses %)."""
    min_x, min_y, max_x, max_y = visible_foreground_bounds(image)
    height = max_y - min_y + 1
    band = max(1, height // 8)

    def average_width(y_start: int, y_end: int) -> float:
        widths: list[int] = []
        for y in range(y_start, y_end):
            xs = [x for x in range(min_x, max_x + 1) if image.getpixel((x, y)) != WHITE_BACKGROUND]
            if xs:
                widths.append(max(xs) - min(xs) + 1)
        if not widths:
            return 0.0
        return sum(widths) / len(widths)

    waist = average_width(min_y, min_y + band)
    hem = average_width(max_y - band + 1, max_y + 1)
    mid = average_width(min_y + height // 3, min_y + 2 * height // 3)
    bbox_w = max_x - min_x + 1
    return {
        "bbox_width_fraction": bbox_w / CANVAS_SIZE,
        "waist_width_fraction": waist / CANVAS_SIZE,
        "mid_width_fraction": mid / CANVAS_SIZE,
        "hem_width_fraction": hem / CANVAS_SIZE,
        "hem_to_waist_ratio": hem / waist if waist else 0.0,
    }


def _to_design_polygons(
    polygons: tuple[tuple[tuple[float, float], ...], ...],
) -> list[list[tuple[float, float]]]:
    return [[(x * DESIGN_WIDTH, y * DESIGN_HEIGHT) for x, y in polygon] for polygon in polygons]


def _polygon_set_bounds(
    polygons: list[list[tuple[float, float]]],
) -> tuple[float, float, float, float]:
    xs = [x for polygon in polygons for x, _ in polygon]
    ys = [y for polygon in polygons for _, y in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _center_and_scale_polygons(
    spec: TemplateSpec,
    *,
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
) -> tuple[list[list[tuple[int, int]]], list[list[tuple[int, int]]]]:
    """Center each silhouette's fill bbox on canvas and scale to the margin box."""
    fill_polys = _to_design_polygons(spec.polygons)
    cutout_polys = _to_design_polygons(spec.cutouts)
    min_x, min_y, max_x, max_y = _polygon_set_bounds(fill_polys)
    bbox_w = max(max_x - min_x, 1.0)
    bbox_h = max(max_y - min_y, 1.0)
    bbox_cx = (min_x + max_x) / 2.0
    bbox_cy = (min_y + max_y) / 2.0

    max_side = canvas_size * (1.0 - 2.0 * margin_fraction)
    scale = max_side / max(bbox_w, bbox_h)
    canvas_cx = canvas_size / 2.0
    canvas_cy = canvas_size / 2.0

    def transform(polygons: list[list[tuple[float, float]]]) -> list[list[tuple[int, int]]]:
        transformed: list[list[tuple[int, int]]] = []
        for polygon in polygons:
            points: list[tuple[int, int]] = []
            for x, y in polygon:
                px = int(round((x - bbox_cx) * scale + canvas_cx))
                py = int(round((y - bbox_cy) * scale + canvas_cy))
                points.append((px, py))
            transformed.append(points)
        return transformed

    return transform(fill_polys), transform(cutout_polys)


def scale_polygons_to_canvas(
    spec: TemplateSpec,
    *,
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
) -> list[list[tuple[int, int]]]:
    fill_polys, _ = _center_and_scale_polygons(
        spec,
        canvas_size=canvas_size,
        margin_fraction=margin_fraction,
    )
    return fill_polys


def scale_cutouts_to_canvas(
    spec: TemplateSpec,
    *,
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
) -> list[list[tuple[int, int]]]:
    _, cutout_polys = _center_and_scale_polygons(
        spec,
        canvas_size=canvas_size,
        margin_fraction=margin_fraction,
    )
    return cutout_polys


def render_template_png(
    spec: TemplateSpec,
    *,
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
    fill: tuple[int, int, int] = SILHOUETTE_FILL,
) -> Image.Image:
    canvas = Image.new("RGB", (canvas_size, canvas_size), WHITE_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    for polygon in scale_polygons_to_canvas(
        spec,
        canvas_size=canvas_size,
        margin_fraction=margin_fraction,
    ):
        draw.polygon(polygon, fill=fill)
    for polygon in scale_cutouts_to_canvas(
        spec,
        canvas_size=canvas_size,
        margin_fraction=margin_fraction,
    ):
        draw.polygon(polygon, fill=WHITE_BACKGROUND)
    return canvas


def _polygon_to_svg_points(polygon: list[tuple[int, int]]) -> str:
    return " ".join(f"{x},{y}" for x, y in polygon)


def render_template_svg(
    spec: TemplateSpec,
    *,
    canvas_size: int = CANVAS_SIZE,
    margin_fraction: float = MARGIN_FRACTION,
    fill: tuple[int, int, int] = SILHOUETTE_FILL,
) -> str:
    fill_hex = f"#{fill[0]:02x}{fill[1]:02x}{fill[2]:02x}"
    bg_hex = "#ffffff"
    fill_polys, cutout_polys = _center_and_scale_polygons(
        spec,
        canvas_size=canvas_size,
        margin_fraction=margin_fraction,
    )

    root = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": str(canvas_size),
            "height": str(canvas_size),
            "viewBox": f"0 0 {canvas_size} {canvas_size}",
        },
    )
    ET.SubElement(
        root,
        "rect",
        {"width": str(canvas_size), "height": str(canvas_size), "fill": bg_hex},
    )
    for polygon in fill_polys:
        ET.SubElement(
            root,
            "polygon",
            {"points": _polygon_to_svg_points(polygon), "fill": fill_hex},
        )
    for polygon in cutout_polys:
        ET.SubElement(
            root,
            "polygon",
            {"points": _polygon_to_svg_points(polygon), "fill": bg_hex},
        )
    return ET.tostring(root, encoding="unicode")


def make_contact_sheet(
    panels: list[tuple[str, Image.Image]],
    *,
    thumb_size: int = 220,
    cols: int = 3,
    font: ImageFont.ImageFont | None = None,
) -> Image.Image:
    label_font = font or ImageFont.load_default()
    rows = max(1, (len(panels) + cols - 1) // cols)
    header_h = 24
    margin = 10
    cell_w = thumb_size + 2 * margin
    cell_h = thumb_size + header_h + 2 * margin
    sheet_w = cols * cell_w + margin
    sheet_h = rows * cell_h + margin
    sheet = Image.new("RGB", (sheet_w, sheet_h), WHITE_BACKGROUND)
    draw = ImageDraw.Draw(sheet)

    for index, (template_id, image) in enumerate(panels):
        col = index % cols
        row = index // cols
        x = margin + col * cell_w
        y = margin + row * cell_h
        draw.text((x + margin, y), template_id, fill=(20, 20, 20), font=label_font)

        preview = image.copy()
        preview.thumbnail((thumb_size, thumb_size), Image.Resampling.LANCZOS)
        paste_x = x + margin + (thumb_size - preview.width) // 2
        paste_y = y + header_h + margin + (thumb_size - preview.height) // 2
        sheet.paste(preview, (paste_x, paste_y))

    return sheet


def default_bench_root(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root or Path.cwd())
    return root / "bench" / "catalog_templates"


def generate_all_templates(
    *,
    output_root: str | Path,
    sources_dir: str | Path | None = None,
    png_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Write SVG sources, PNG renders, and a contact sheet for every template."""
    resolved_output = Path(output_root)
    resolved_sources = Path(sources_dir or resolved_output / "sources")
    resolved_png = Path(png_dir or resolved_output / "generated")
    resolved_sources.mkdir(parents=True, exist_ok=True)
    resolved_png.mkdir(parents=True, exist_ok=True)

    repo = Path(repo_root or Path.cwd()).resolve()
    entries: list[dict[str, Any]] = []
    contact_panels: list[tuple[str, Image.Image]] = []

    for spec in TEMPLATE_SPECS:
        svg_path = resolved_sources / f"{spec.id}.svg"
        png_path = resolved_png / f"{spec.id}.png"
        svg_path.write_text(render_template_svg(spec), encoding="utf-8")
        png = render_template_png(spec)
        png.save(png_path)
        contact_panels.append((spec.id, png))

        entries.append(
            spec.to_manifest_entry(
                repo_relative_png=png_path.resolve().relative_to(repo).as_posix(),
                repo_relative_svg=svg_path.resolve().relative_to(repo).as_posix(),
            )
        )

    contact_path = resolved_png / "contact_sheet.jpg"
    make_contact_sheet(contact_panels).save(contact_path, quality=92)
    return entries


SOURCE_PROVENANCE: dict[str, Any] = {
    "strategy": "internal_deterministic",
    "online_set_adopted": False,
    "summary": (
        "No single CC0/public-domain online pack covers all five required garment "
        "silhouettes in one coherent front-facing catalog style. Kept repo-owned "
        "polygon definitions; see SOURCES.md for research notes."
    ),
    "research_doc": "bench/catalog_templates/SOURCES.md",
}


def write_manifest(
    *,
    output_root: str | Path,
    entries: list[dict[str, Any]],
) -> Path:
    manifest_path = Path(output_root) / "manifest.json"
    payload = {
        "bench": "catalog_templates",
        "description": (
            "Canonical front-facing garment silhouette templates for catalog layout "
            "and reconstruction geometry targets."
        ),
        "canvas": {
            "size": CANVAS_SIZE,
            "background_rgb": list(WHITE_BACKGROUND),
            "margin_fraction": MARGIN_FRACTION,
            "silhouette_fill_rgb": list(SILHOUETTE_FILL),
            "centering": "visible_foreground_bbox_centered_xy",
        },
        "source_provenance": SOURCE_PROVENANCE,
        "templates": entries,
        "artifacts": {
            "contact_sheet": "bench/catalog_templates/generated/contact_sheet.jpg",
        },
        "categories": {
            "top_full_sleeve": {"role": "top", "sleeve": "full", "top_kind": "generic"},
            "top_half_sleeve": {"role": "top", "sleeve": "half", "top_kind": "generic"},
            "top_sleeveless": {
                "role": "top",
                "sleeve": "sleeveless",
                "top_kind": "generic",
                "geometry_notes": (
                    "Front-facing sleeveless blouse/top: shoulder straps or upper bodice with "
                    "open armhole cutouts, no sleeve polygons, centered catalog proportions."
                ),
            },
            "blazer": {"role": "top", "sleeve": "full", "top_kind": "blazer"},
            "waistcoat_closed": {
                "role": "top",
                "sleeve": None,
                "top_kind": "waistcoat",
                "geometry_notes": (
                    "Front-facing closed waistcoat/vest: sleeveless structured shoulders "
                    "and armholes, V-neck lapels, hip-length fitted torso, buttoned center "
                    "front with no open garment gap."
                ),
            },
            "dress_knee_length_half_sleeve": {
                "role": "top",
                "sleeve": "half",
                "top_kind": "dress",
                "geometry_notes": (
                    "Front-facing one-piece knee-length dress with half/short sleeves; "
                    "continuous bodice-to-skirt silhouette with no waistband separation."
                ),
            },
            "dress_knee_length_full_sleeve": {
                "role": "dress",
                "sleeve": "full",
                "top_kind": "dress",
                "geometry_notes": (
                    "Front-facing one-piece knee-length dress with full/long sleeves; "
                    "continuous bodice-to-skirt silhouette with no waistband separation."
                ),
            },
            "skirt": {"role": "bottom", "bottom_kind": "skirt"},
            "skirt_pencil": {
                "role": "bottom",
                "bottom_kind": "skirt_pencil",
                "geometry_notes": (
                    "Front-facing pencil skirt; rendered waist ~34%, hip/body ~47%, hem ~43% "
                    "of 512 canvas width (hem/waist ~1.25). v1 narrow backup preserved as "
                    "skirt_pencil_v1_narrow.png (~13% waist)."
                ),
            },
            "pants": {
                "role": "bottom",
                "bottom_kind": "pants",
                "geometry_notes": (
                    "Front-facing trousers with a narrow waist band and split-leg inner "
                    "separation beginning at y=0.10 (legacy v3 silhouette)."
                ),
            },
        },
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate canonical 512x512 catalog garment template assets."
    )
    parser.add_argument(
        "--output-root",
        default=str(default_bench_root()),
        help="Bench root containing sources/ and generated/ (default: bench/catalog_templates).",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root for manifest path entries.",
    )
    args = parser.parse_args()

    try:
        entries = generate_all_templates(
            output_root=args.output_root,
            repo_root=args.repo_root,
        )
        manifest_path = write_manifest(output_root=args.output_root, entries=entries)
        print(f"wrote {len(entries)} templates under {args.output_root}")
        print(f"contact sheet: {Path(args.output_root) / 'generated' / 'contact_sheet.jpg'}")
        print(f"manifest: {manifest_path}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
