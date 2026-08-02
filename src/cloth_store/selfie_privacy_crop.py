"""Deterministic neck-down privacy crops for mirror-selfie review candidates.

Non-generative: crops/reframes existing blur-only refocus outputs (or re-renders
from the same source crop spec) without face blurring, inpainting, upscaling, or
model/API calls.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from cloth_store.catalog_hash import sha256_file
from cloth_store.selfie_refocus import (
    DEFAULT_OUTPUT_ROOT,
    PRIMARY_ASPECT,
    PortraitCropSpec,
    load_fixture_metadata,
    load_person_mask,
    render_crop_only,
    render_crop_refocused,
)

NECK_DOWN_VARIANT = "crop_neck_down"
NECK_DOWN_METHOD = "neck_down_privacy_v1"
NECK_DOWN_METADATA_SUFFIX = ".metadata.json"
DEFAULT_ASPECT_LABEL = "4:5"
DEFAULT_FINAL_SELFIES_ROOT = Path("final_selfies")
DEFAULT_OVERRIDES_PATH = Path("bench/selfie_refocus/privacy_cutoff_overrides.json")
PRIVACY_FLOOR_FRACTION_OF_PERSON_HEIGHT = 0.17
PRIVACY_QC_PASS = "pass"
PRIVACY_QC_LIMITATION = "limitation"
PRIVACY_QC_FAIL = "fail"
PRIVACY_QC_USER_APPROVED = "user_approved"
SOURCE_VARIANT_ORIGINAL = "original"
RENDER_MODE_CROP_ONLY = "crop_only"
RENDER_MODE_SUBCROP = "refocused_subcrop"


@dataclass(frozen=True)
class PrivacyFixtureOverride:
    """Reviewed per-fixture privacy override from the registry."""

    face_bottom_cutoff_y_normalized: float | None = None
    provenance: str | None = None
    source_variant: str | None = None
    render_mode: str | None = None
    user_approved: bool = False
    qc_status: str | None = None
    note: str | None = None
    reviewed_at: str | None = None

    @classmethod
    def from_registry_entry(cls, entry: dict[str, Any] | None) -> PrivacyFixtureOverride | None:
        if not entry:
            return None
        return cls(
            face_bottom_cutoff_y_normalized=entry.get("face_bottom_cutoff_y_normalized"),
            provenance=entry.get("provenance"),
            source_variant=entry.get("source_variant"),
            render_mode=entry.get("render_mode"),
            user_approved=bool(
                entry.get("user_approved") or entry.get("qc_status") == PRIVACY_QC_USER_APPROVED
            ),
            qc_status=entry.get("qc_status"),
            note=entry.get("note"),
            reviewed_at=entry.get("reviewed_at"),
        )


@dataclass(frozen=True)
class NeckDownCropConfig:
    """Explicit face-bottom cutoff encoded as normalized source-image Y."""

    face_bottom_cutoff_y_normalized: float
    face_bottom_provenance: str
    aspect_label: str = DEFAULT_ASPECT_LABEL
    aspect_ratio: float = PRIMARY_ASPECT
    privacy_purpose: str = "neck_down_face_exclusion"
    face_bottom_margin_fraction_of_person_height: float = 0.03
    source_variant: str = "crop_refocused"

    @property
    def cutoff_y_normalized(self) -> float:
        """Backward-compatible alias for ``face_bottom_cutoff_y_normalized``."""
        return self.face_bottom_cutoff_y_normalized

    @property
    def cutoff_provenance(self) -> str:
        """Backward-compatible alias for ``face_bottom_provenance``."""
        return self.face_bottom_provenance

    @property
    def cutoff_margin_fraction_of_person_height(self) -> float:
        """Backward-compatible alias for the face-bottom margin fraction."""
        return self.face_bottom_margin_fraction_of_person_height

    def validate(self) -> None:
        if not 0.0 <= self.face_bottom_cutoff_y_normalized < 1.0:
            raise ValueError(
                "face_bottom_cutoff_y_normalized must be in [0, 1), "
                f"got {self.face_bottom_cutoff_y_normalized!r}"
            )
        if self.aspect_ratio <= 0:
            raise ValueError("aspect_ratio must be positive")
        if not self.face_bottom_provenance.strip():
            raise ValueError("face_bottom_provenance must be non-empty")


@dataclass(frozen=True)
class NeckDownCropGeometry:
    """Resolved crop geometry for a neck-down privacy variant."""

    config: NeckDownCropConfig
    source_image_width: int
    source_image_height: int
    base_crop: PortraitCropSpec
    neck_down_crop: PortraitCropSpec
    sub_crop_from_refocused: tuple[int, int, int, int]
    retained_person_top_y: int
    retained_person_bottom_y: int
    face_exclusion_rows: int
    collarbone_cutoff_y: int | None = None

    @property
    def output_width(self) -> int:
        x0, _, x1, _ = self.sub_crop_from_refocused
        return x1 - x0

    @property
    def output_height(self) -> int:
        _, y0, _, y1 = self.sub_crop_from_refocused
        return y1 - y0


@dataclass(frozen=True)
class NeckDownCandidateResult:
    fixture_id: str
    geometry: NeckDownCropGeometry
    output_path: str
    metadata_path: str
    source_refocused_path: str
    source_variant: str
    output_sha256: str
    generated_or_reused: str
    qc_status: str
    qc_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrivacyCropBatchResult:
    processed: list[str]
    reused: list[str]
    failed: dict[str, str]
    limitations: dict[str, list[str]]


def _person_rows_in_base_crop(
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
) -> tuple[np.ndarray, np.ndarray, int, int, int]:
    crop_mask = person_mask[base_crop.y0 : base_crop.y1, base_crop.x0 : base_crop.x1]
    row_occ = crop_mask.sum(axis=1)
    person_rows = np.where(crop_mask.any(axis=1))[0]
    if person_rows.size == 0:
        raise ValueError("person mask empty inside base crop")
    person_top = int(person_rows[0])
    person_bottom = int(person_rows[-1])
    person_height = max(1, person_bottom - person_top)
    return crop_mask, row_occ, person_top, person_bottom, person_height


def estimate_face_bottom_cutoff_y_from_mask(
    *,
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
    image_height: int,
    margin_fraction_of_person_height: float = 0.03,
) -> tuple[int, str]:
    """Estimate source-Y immediately below the jaw/face using a mask width profile."""
    _, row_occ, person_top, person_bottom, person_height = _person_rows_in_base_crop(
        person_mask, base_crop
    )
    head_end = person_top + max(12, int(person_height * 0.22))
    head_segment = row_occ[person_top:head_end].astype(np.float64)
    if head_segment.size < 8:
        cutoff_row = person_top + int(person_height * 0.16)
        provenance = "mask_person_top_margin_v1"
    else:
        smooth = np.convolve(head_segment, np.ones(5) / 5.0, mode="same")
        peak = int(np.argmax(smooth[: max(4, len(smooth) // 2)]))
        post_peak = smooth[peak : min(len(smooth), peak + 48)]
        jaw_row = peak
        threshold = max(1.0, smooth[peak] * 0.72)
        for idx in range(1, len(post_peak)):
            if post_peak[idx] <= threshold:
                jaw_row = peak + idx
                break
        margin = max(3, int(round(person_height * margin_fraction_of_person_height)))
        cutoff_row = jaw_row + margin
        provenance = "mask_face_bottom_jaw_v1"

    cutoff_row = min(max(person_top + 1, cutoff_row), person_bottom - 1)
    cutoff_y = base_crop.y0 + cutoff_row
    cutoff_y = max(base_crop.y0 + 1, min(cutoff_y, base_crop.y1 - 2))
    return cutoff_y, provenance


def estimate_collarbone_cutoff_y_from_mask(
    *,
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
    image_height: int,
    margin_fraction_of_person_height: float = 0.06,
) -> tuple[int, str]:
    """Estimate an over-conservative collarbone cutoff (reference only)."""
    _, row_occ, person_top, person_bottom, person_height = _person_rows_in_base_crop(
        person_mask, base_crop
    )
    search_end = person_top + max(8, int(person_height * 0.45))
    segment = row_occ[person_top:search_end].astype(np.float64)
    if segment.size < 5:
        cutoff_row = person_top + int(person_height * 0.12)
        provenance = "mask_person_top_margin_v1"
    else:
        smooth = np.convolve(segment, np.ones(5) / 5.0, mode="same")
        peak = int(np.argmax(smooth[: max(3, len(smooth) // 2)]))
        post_peak = smooth[peak : min(len(smooth), peak + 80)]
        neck_offset = peak
        if post_peak.size >= 3:
            for idx in range(1, len(post_peak) - 1):
                if post_peak[idx] <= post_peak[idx - 1] and post_peak[idx] <= post_peak[idx + 1]:
                    neck_offset = peak + idx
                    break
        margin = max(4, int(round(person_height * margin_fraction_of_person_height)))
        cutoff_row = person_top + neck_offset + margin
        provenance = "mask_collarbone_minimum_v1"

    cutoff_row = min(max(person_top + 1, cutoff_row), person_bottom - 1)
    cutoff_y = base_crop.y0 + cutoff_row
    cutoff_y = max(base_crop.y0 + 1, min(cutoff_y, base_crop.y1 - 2))
    return cutoff_y, provenance


def estimate_neck_cutoff_y_from_mask(
    *,
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
    image_height: int,
    margin_fraction_of_person_height: float = 0.06,
) -> tuple[int, str]:
    """Backward-compatible alias for the collarbone cutoff estimator."""
    return estimate_collarbone_cutoff_y_from_mask(
        person_mask=person_mask,
        base_crop=base_crop,
        image_height=image_height,
        margin_fraction_of_person_height=margin_fraction_of_person_height,
    )


def compute_neck_down_crop(
    *,
    image_width: int,
    image_height: int,
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
    config: NeckDownCropConfig,
    collarbone_cutoff_y: int | None = None,
) -> NeckDownCropGeometry:
    """Compute a portrait neck-down crop anchored at the face-bottom cutoff."""
    config.validate()
    face_bottom_y = int(round(config.face_bottom_cutoff_y_normalized * image_height))
    face_bottom_y = max(base_crop.y0 + 1, min(face_bottom_y, base_crop.y1 - 2))

    y0 = face_bottom_y
    y1 = base_crop.y1
    crop_h = y1 - y0
    if crop_h < 32:
        raise ValueError("neck-down crop height too small")

    max_w = min(image_width, base_crop.x1 - base_crop.x0)
    crop_w = min(int(round(crop_h * config.aspect_ratio)), max_w)
    if crop_w < 32:
        raise ValueError("neck-down crop width too small")

    region_mask = person_mask[y0:y1, base_crop.x0 : base_crop.x1]
    if not region_mask.any():
        raise ValueError("person mask empty below face-bottom cutoff")
    cols = np.where(region_mask.any(axis=0))[0]
    sub_cx = (cols[0] + cols[-1]) / 2.0 + base_crop.x0

    cx0 = int(round(sub_cx - crop_w / 2.0))
    cx1 = cx0 + crop_w
    if cx0 < base_crop.x0:
        shift = base_crop.x0 - cx0
        cx0 += shift
        cx1 += shift
    if cx1 > base_crop.x1:
        shift = cx1 - base_crop.x1
        cx0 -= shift
        cx1 -= shift
    cx0 = max(base_crop.x0, cx0)
    cx1 = min(base_crop.x1, cx0 + crop_w)

    cx0 = max(0, min(cx0, image_width - 1))
    cx1 = min(image_width, max(cx0 + 1, cx1))
    y0 = max(0, min(y0, image_height - 2))
    y1 = min(image_height, max(y0 + 1, y1))

    neck_down = PortraitCropSpec(
        x0=cx0,
        y0=y0,
        x1=cx1,
        y1=y1,
        aspect_ratio=round((cx1 - cx0) / (y1 - y0), 4),
        aspect_label=config.aspect_label,
        padding_fraction=base_crop.padding_fraction,
        output_width=cx1 - cx0,
        output_height=y1 - y0,
    )

    sub_x0 = cx0 - base_crop.x0
    sub_y0 = y0 - base_crop.y0
    sub_x1 = sub_x0 + neck_down.output_width
    sub_y1 = sub_y0 + neck_down.output_height
    if sub_x1 > base_crop.output_width or sub_y1 > base_crop.output_height:
        raise ValueError("neck-down sub-crop exceeds base refocused bounds")

    person_rows = np.where(person_mask.any(axis=1))[0]
    face_exclusion_rows = max(0, y0 - int(person_rows[0]))

    return NeckDownCropGeometry(
        config=config,
        source_image_width=image_width,
        source_image_height=image_height,
        base_crop=base_crop,
        neck_down_crop=neck_down,
        sub_crop_from_refocused=(sub_x0, sub_y0, sub_x1, sub_y1),
        retained_person_top_y=y0,
        retained_person_bottom_y=int(person_rows[-1]),
        face_exclusion_rows=face_exclusion_rows,
        collarbone_cutoff_y=collarbone_cutoff_y,
    )


def render_neck_down_from_refocused(
    refocused_rgb: Image.Image,
    sub_crop: tuple[int, int, int, int],
) -> Image.Image:
    """Crop an existing blur-only refocused portrait without resampling/stretch."""
    x0, y0, x1, y1 = sub_crop
    width, height = refocused_rgb.size
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height or x1 <= x0 or y1 <= y0:
        raise ValueError("invalid neck-down sub-crop for refocused image")
    if (x1 - x0, y1 - y0) > (width, height):
        raise ValueError("neck-down crop would upscale refocused image")
    return refocused_rgb.crop((x0, y0, x1, y1))


def render_neck_down_from_source(
    source_rgb: Image.Image,
    person_mask: np.ndarray,
    geometry: NeckDownCropGeometry,
) -> Image.Image:
    """Re-render blur-only refocus at the neck-down crop (no generative calls)."""
    return render_crop_refocused(source_rgb, geometry.neck_down_crop, person_mask)


def build_neck_down_config_from_mask(
    *,
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
    image_height: int,
    margin_fraction_of_person_height: float = 0.03,
    manual_face_bottom_cutoff_y_normalized: float | None = None,
    manual_provenance: str | None = None,
    manual_cutoff_y_normalized: float | None = None,
) -> NeckDownCropConfig:
    manual_value = manual_face_bottom_cutoff_y_normalized
    if manual_value is None:
        manual_value = manual_cutoff_y_normalized
    if manual_value is not None:
        provenance = manual_provenance or "manual_review_face_bottom_cutoff_v1"
        face_bottom_y_normalized = manual_value
    else:
        cutoff_y, provenance = estimate_face_bottom_cutoff_y_from_mask(
            person_mask=person_mask,
            base_crop=base_crop,
            image_height=image_height,
            margin_fraction_of_person_height=margin_fraction_of_person_height,
        )
        face_bottom_y_normalized = round(cutoff_y / image_height, 6)
    return NeckDownCropConfig(
        face_bottom_cutoff_y_normalized=face_bottom_y_normalized,
        face_bottom_provenance=provenance,
        face_bottom_margin_fraction_of_person_height=margin_fraction_of_person_height,
    )


def load_privacy_cutoff_overrides(
    repo_root: Path,
    overrides_path: Path | None = None,
) -> dict[str, Any]:
    path = overrides_path or (repo_root / DEFAULT_OVERRIDES_PATH)
    if not path.is_file():
        return {"schema_version": 1, "overrides": {}, "defaults": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("overrides"), dict):
        raise ValueError(f"invalid privacy overrides file: {path}")
    return payload


def get_fixture_privacy_override(
    overrides: dict[str, Any],
    fixture_id: str,
) -> PrivacyFixtureOverride | None:
    return PrivacyFixtureOverride.from_registry_entry(
        overrides.get("overrides", {}).get(fixture_id)
    )


def build_original_privacy_base_crop(
    *,
    base_crop: PortraitCropSpec,
    person_mask: np.ndarray,
    image_width: int,
    image_height: int,
) -> PortraitCropSpec:
    """Extend the portrait base crop to retain feet on the original source photo."""
    person_rows = np.where(person_mask.any(axis=1))[0]
    if person_rows.size == 0:
        raise ValueError("person mask empty for original privacy base crop")
    y1 = image_height
    y0 = min(base_crop.y0, int(person_rows[0]))
    return PortraitCropSpec(
        x0=base_crop.x0,
        y0=y0,
        x1=base_crop.x1,
        y1=y1,
        aspect_ratio=round((base_crop.x1 - base_crop.x0) / max(1, y1 - y0), 4),
        aspect_label=base_crop.aspect_label,
        padding_fraction=base_crop.padding_fraction,
        output_width=base_crop.x1 - base_crop.x0,
        output_height=y1 - y0,
    )


def resolve_privacy_source_path(
    *,
    fixture_id: str,
    repo_root: Path,
    source_metadata: dict[str, Any],
    candidate_root: Path,
    prefer_final_selfies: bool = True,
    source_path_override: Path | None = None,
    fixture_override: PrivacyFixtureOverride | None = None,
) -> tuple[Path, str]:
    """Return the approved privacy source path and its variant name."""
    if fixture_override and fixture_override.source_variant == SOURCE_VARIANT_ORIGINAL:
        original_path = repo_root / source_metadata["source_path"]
        if not original_path.is_file():
            raise FileNotFoundError(f"missing original privacy source: {original_path}")
        return original_path, SOURCE_VARIANT_ORIGINAL

    if source_path_override is not None:
        if not source_path_override.is_file():
            raise FileNotFoundError(f"missing privacy source: {source_path_override}")
        for variant in ("crop_refocused", "crop_only"):
            if source_path_override.name == f"{variant}.jpg":
                return source_path_override, variant
        return source_path_override, source_metadata.get("recommended_variant", "crop_refocused")

    preferred = source_metadata.get("recommended_variant", "crop_refocused")
    variant_order = []
    for variant in (preferred, "crop_refocused", "crop_only"):
        if variant not in variant_order:
            variant_order.append(variant)

    for variant in variant_order:
        if prefer_final_selfies:
            final_path = repo_root / DEFAULT_FINAL_SELFIES_ROOT / fixture_id / f"{variant}.jpg"
            if final_path.is_file():
                return final_path, variant
        rel = source_metadata.get("variants", {}).get(variant)
        if rel:
            bench_path = repo_root / rel
            if bench_path.is_file():
                return bench_path, variant
        fixture_path = candidate_root / fixture_id / f"{variant}.jpg"
        if fixture_path.is_file():
            return fixture_path, variant

    raise FileNotFoundError(f"missing privacy source variant for {fixture_id}")


def resolve_refocused_source_path(
    *,
    fixture_id: str,
    repo_root: Path,
    source_metadata: dict[str, Any],
    candidate_root: Path,
    prefer_final_selfies: bool = True,
    refocused_source_path: Path | None = None,
) -> Path:
    if refocused_source_path is not None:
        path = refocused_source_path
        if not path.is_file():
            raise FileNotFoundError(f"missing refocused source: {path}")
        return path

    if prefer_final_selfies:
        final_path = repo_root / DEFAULT_FINAL_SELFIES_ROOT / fixture_id / "crop_refocused.jpg"
        if final_path.is_file():
            return final_path

    refocused_rel = source_metadata.get("variants", {}).get("crop_refocused")
    if refocused_rel:
        bench_path = repo_root / refocused_rel
        if bench_path.is_file():
            return bench_path

    fixture_path = candidate_root / fixture_id / "crop_refocused.jpg"
    if fixture_path.is_file():
        return fixture_path

    raise FileNotFoundError(f"missing crop_refocused for {fixture_id}")


def build_neck_down_config_auto(
    *,
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
    image_height: int,
    source_metadata: dict[str, Any] | None = None,
    margin_fraction_of_person_height: float = 0.03,
    privacy_floor_fraction_of_person_height: float = PRIVACY_FLOOR_FRACTION_OF_PERSON_HEIGHT,
) -> NeckDownCropConfig:
    jaw_y, jaw_provenance = estimate_face_bottom_cutoff_y_from_mask(
        person_mask=person_mask,
        base_crop=base_crop,
        image_height=image_height,
        margin_fraction_of_person_height=margin_fraction_of_person_height,
    )
    _, _, person_top, _, person_height = _person_rows_in_base_crop(person_mask, base_crop)
    floor_y = (
        base_crop.y0
        + person_top
        + int(round(person_height * privacy_floor_fraction_of_person_height))
    )
    cutoff_candidates = [jaw_y, floor_y]
    provenance = jaw_provenance

    if source_metadata and "person_bbox" in source_metadata:
        bbox = source_metadata["person_bbox"]["box"]
        bbox_top_y = int(round(bbox[1] * image_height))
        bbox_height = max(1, int(round((bbox[3] - bbox[1]) * image_height)))
        bbox_chin_y = bbox_top_y + int(round(bbox_height * 0.145))
        cutoff_candidates.append(bbox_chin_y)
        if bbox_chin_y > jaw_y:
            provenance = f"{jaw_provenance}+bbox_chin_v1"

    cutoff_y = max(cutoff_candidates)
    if cutoff_y > jaw_y and cutoff_y == floor_y:
        provenance = f"{jaw_provenance}+privacy_floor_v1"
    cutoff_y = max(base_crop.y0 + 1, min(cutoff_y, base_crop.y1 - 2))
    return NeckDownCropConfig(
        face_bottom_cutoff_y_normalized=round(cutoff_y / image_height, 6),
        face_bottom_provenance=provenance,
        face_bottom_margin_fraction_of_person_height=margin_fraction_of_person_height,
    )


def build_neck_down_config_for_fixture(
    *,
    fixture_id: str,
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
    image_height: int,
    overrides: dict[str, Any],
    source_metadata: dict[str, Any] | None = None,
) -> NeckDownCropConfig:
    defaults = overrides.get("defaults", {})
    margin = float(defaults.get("face_bottom_margin_fraction_of_person_height", 0.03))
    floor_fraction = float(
        defaults.get(
            "privacy_floor_fraction_of_person_height",
            PRIVACY_FLOOR_FRACTION_OF_PERSON_HEIGHT,
        )
    )
    entry = overrides.get("overrides", {}).get(fixture_id)
    fixture_override = PrivacyFixtureOverride.from_registry_entry(entry)
    source_variant = (
        fixture_override.source_variant
        if fixture_override and fixture_override.source_variant
        else "crop_refocused"
    )
    if entry and entry.get("face_bottom_cutoff_y_normalized") is not None:
        return NeckDownCropConfig(
            face_bottom_cutoff_y_normalized=float(entry["face_bottom_cutoff_y_normalized"]),
            face_bottom_provenance=str(
                entry.get("provenance", "manual_review_face_bottom_cutoff_v1")
            ),
            face_bottom_margin_fraction_of_person_height=margin,
            source_variant=source_variant,
        )
    auto_config = build_neck_down_config_auto(
        person_mask=person_mask,
        base_crop=base_crop,
        image_height=image_height,
        source_metadata=source_metadata,
        margin_fraction_of_person_height=margin,
        privacy_floor_fraction_of_person_height=floor_fraction,
    )
    return NeckDownCropConfig(
        face_bottom_cutoff_y_normalized=auto_config.face_bottom_cutoff_y_normalized,
        face_bottom_provenance=auto_config.face_bottom_provenance,
        face_bottom_margin_fraction_of_person_height=margin,
        source_variant=source_variant,
    )


def assess_privacy_qc(
    *,
    geometry: NeckDownCropGeometry,
    person_mask: np.ndarray,
    base_crop: PortraitCropSpec,
    source_metadata: dict[str, Any],
    image_height: int,
    source_variant: str = "crop_refocused",
) -> tuple[str, list[str]]:
    notes: list[str] = []
    crop_mask = person_mask[base_crop.y0 : base_crop.y1, base_crop.x0 : base_crop.x1]
    person_rows = np.where(crop_mask.any(axis=1))[0]
    if person_rows.size == 0:
        return PRIVACY_QC_FAIL, ["person_mask_empty"]

    person_top = int(person_rows[0])
    person_bottom = int(person_rows[-1])
    person_height = max(1, person_bottom - person_top)
    face_bottom_row = geometry.neck_down_crop.y0 - base_crop.y0

    jaw_y, _ = estimate_face_bottom_cutoff_y_from_mask(
        person_mask=person_mask,
        base_crop=base_crop,
        image_height=image_height,
        margin_fraction_of_person_height=0.0,
    )
    jaw_row = jaw_y - base_crop.y0
    privacy_floor_row = person_top + int(
        round(person_height * PRIVACY_FLOOR_FRACTION_OF_PERSON_HEIGHT)
    )
    min_safe_row = max(jaw_row, privacy_floor_row)
    if face_bottom_row < min_safe_row:
        return PRIVACY_QC_FAIL, ["face_pixels_may_remain_above_cutoff"]

    shoulder_row = person_top + int(person_height * 0.20)
    if face_bottom_row > shoulder_row + int(person_height * 0.08):
        notes.append("shoulder_line_may_be_partially_clipped")

    if geometry.neck_down_crop.y1 < base_crop.y1 - 8:
        feet_margin = base_crop.y1 - geometry.retained_person_bottom_y
        if feet_margin > max(24, int(person_height * 0.08)):
            notes.append("feet_may_be_partially_clipped_in_source")

    metrics = source_metadata.get("metrics", {})
    if metrics.get("subject_clipped") and source_variant != SOURCE_VARIANT_ORIGINAL:
        notes.append("source_crop_subject_clipped")

    if source_metadata.get("review_required") and source_variant != SOURCE_VARIANT_ORIGINAL:
        notes.append("source_fixture_review_required")

    if notes:
        return PRIVACY_QC_LIMITATION, notes
    return PRIVACY_QC_PASS, []


def privacy_metadata_reuse_eligible(
    existing: dict[str, Any],
    *,
    source_variant_sha256: str,
    config: NeckDownCropConfig,
    source_variant: str,
) -> bool:
    if existing.get("privacy_method") != NECK_DOWN_METHOD:
        return False
    if existing.get("source_variant") != source_variant:
        return False
    if existing.get("source_variant_sha256") != source_variant_sha256:
        return False
    cutoff = existing.get("face_bottom_cutoff", {})
    if cutoff.get("y_normalized") != config.face_bottom_cutoff_y_normalized:
        return False
    return cutoff.get("provenance") == config.face_bottom_provenance


def render_neck_down_from_original(
    source_rgb: Image.Image,
    neck_down_crop: PortraitCropSpec,
) -> Image.Image:
    """Crop the original source photo without blur/refocus treatment."""
    return render_crop_only(source_rgb, neck_down_crop)


def serialize_neck_down_metadata(
    *,
    fixture_id: str,
    geometry: NeckDownCropGeometry,
    source_metadata: dict[str, Any],
    source_refocused_path: Path,
    output_path: Path,
    source_variant: str,
    qc_status: str,
    qc_notes: list[str],
    render_mode: str,
    fixture_override: PrivacyFixtureOverride | None = None,
) -> dict[str, Any]:
    sub_x0, sub_y0, sub_x1, sub_y1 = geometry.sub_crop_from_refocused
    image_height = geometry.source_image_height
    face_bottom_y = geometry.neck_down_crop.y0
    collarbone_y = geometry.collarbone_cutoff_y
    crop_block = {
        "x0": geometry.neck_down_crop.x0,
        "y0": geometry.neck_down_crop.y0,
        "x1": geometry.neck_down_crop.x1,
        "y1": geometry.neck_down_crop.y1,
        "output_width": geometry.neck_down_crop.output_width,
        "output_height": geometry.neck_down_crop.output_height,
    }
    payload: dict[str, Any] = {
        "fixture_id": fixture_id,
        "privacy_method": NECK_DOWN_METHOD,
        "privacy_purpose": geometry.config.privacy_purpose,
        "source_variant": source_variant,
        "render_mode": render_mode,
        "source_refocused_path": str(source_refocused_path),
        "source_variant_sha256": sha256_file(source_refocused_path),
        "source_refocused_sha256": sha256_file(source_refocused_path),
        "source_metadata_path": f"bench/selfie_refocus/candidates/{fixture_id}/metadata.json",
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "base_crop": asdict(geometry.base_crop),
        "neck_down_crop": asdict(geometry.neck_down_crop),
        "sub_crop_from_refocused": {
            "x0": sub_x0,
            "y0": sub_y0,
            "x1": sub_x1,
            "y1": sub_y1,
            "output_width": geometry.output_width,
            "output_height": geometry.output_height,
        },
        "face_bottom_cutoff": {
            "y_normalized": geometry.config.face_bottom_cutoff_y_normalized,
            "provenance": geometry.config.face_bottom_provenance,
            "margin_fraction_of_person_height": (
                geometry.config.face_bottom_margin_fraction_of_person_height
            ),
            "source_y_px": face_bottom_y,
            "face_exclusion_rows": geometry.face_exclusion_rows,
        },
        "framing": {
            "aspect_label": geometry.config.aspect_label,
            "aspect_ratio": geometry.neck_down_crop.aspect_ratio,
            "retained_person_top_y": geometry.retained_person_top_y,
            "retained_person_bottom_y": geometry.retained_person_bottom_y,
            "top_anchor": "face_bottom_cutoff",
            "upscale_applied": False,
            "generative_calls": 0,
        },
        "parameters": source_metadata.get("parameters", {}),
        "qc": {
            "status": qc_status,
            "notes": qc_notes,
            "face_pixels_present": qc_status == PRIVACY_QC_FAIL,
        },
    }
    if render_mode == RENDER_MODE_CROP_ONLY:
        payload["crop_from_source"] = crop_block
    if fixture_override and fixture_override.user_approved:
        payload["user_approved"] = True
        if fixture_override.reviewed_at:
            payload["user_approved_at"] = fixture_override.reviewed_at
        if fixture_override.note:
            payload["user_approved_note"] = fixture_override.note
    if collarbone_y is not None:
        payload["collarbone_cutoff_reference"] = {
            "y_normalized": round(collarbone_y / image_height, 6),
            "source_y_px": collarbone_y,
            "provenance": "mask_collarbone_minimum_v1",
            "note": "over_conservative_reference_not_used_for_crop",
        }
    return payload


def generate_neck_down_review_candidate(
    *,
    fixture_id: str,
    repo_root: Path,
    candidate_root: Path = DEFAULT_OUTPUT_ROOT,
    config: NeckDownCropConfig | None = None,
    prefer_refocused_subcrop: bool = True,
    prefer_final_selfies_source: bool = True,
    refocused_source_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
    force: bool = False,
) -> NeckDownCandidateResult:
    """Write ``crop_neck_down.jpg`` + metadata under the bench candidate directory."""
    fixture_dir = candidate_root / fixture_id
    metadata_path = fixture_dir / "metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"missing refocus metadata: {metadata_path}")

    source_metadata = load_fixture_metadata(metadata_path)
    source_path = repo_root / source_metadata["source_path"]
    resolved_overrides = overrides or load_privacy_cutoff_overrides(repo_root)
    fixture_override = get_fixture_privacy_override(resolved_overrides, fixture_id)
    source_variant_path, source_variant = resolve_privacy_source_path(
        fixture_id=fixture_id,
        repo_root=repo_root,
        source_metadata=source_metadata,
        candidate_root=candidate_root,
        prefer_final_selfies=prefer_final_selfies_source,
        source_path_override=refocused_source_path,
        fixture_override=fixture_override,
    )
    source_variant_sha256 = sha256_file(source_variant_path)

    mask_rel = source_metadata.get("artifacts", {}).get("person_mask")
    if not mask_rel:
        raise ValueError("source metadata missing person_mask artifact")
    person_mask = load_person_mask(repo_root / mask_rel)

    output_path = fixture_dir / f"{NECK_DOWN_VARIANT}.jpg"
    metadata_out_path = fixture_dir / f"{NECK_DOWN_VARIANT}{NECK_DOWN_METADATA_SUFFIX}"

    with Image.open(source_path) as source_image:
        image_width, image_height = source_image.size
        crop_dict = source_metadata["crop"]
        portrait_base_crop = PortraitCropSpec(
            x0=int(crop_dict["x0"]),
            y0=int(crop_dict["y0"]),
            x1=int(crop_dict["x1"]),
            y1=int(crop_dict["y1"]),
            aspect_ratio=float(crop_dict["aspect_ratio"]),
            aspect_label=str(crop_dict["aspect_label"]),
            padding_fraction=float(crop_dict["padding_fraction"]),
            output_width=int(crop_dict["output_width"]),
            output_height=int(crop_dict["output_height"]),
        )
        use_original_source = source_variant == SOURCE_VARIANT_ORIGINAL
        base_crop = (
            build_original_privacy_base_crop(
                base_crop=portrait_base_crop,
                person_mask=person_mask,
                image_width=image_width,
                image_height=image_height,
            )
            if use_original_source
            else portrait_base_crop
        )
        resolved_config = config or build_neck_down_config_for_fixture(
            fixture_id=fixture_id,
            person_mask=person_mask,
            base_crop=portrait_base_crop,
            image_height=image_height,
            overrides=resolved_overrides,
            source_metadata=source_metadata,
        )
        render_mode = RENDER_MODE_CROP_ONLY if use_original_source else RENDER_MODE_SUBCROP
        if fixture_override and fixture_override.user_approved and output_path.is_file():
            existing = (
                json.loads(metadata_out_path.read_text(encoding="utf-8"))
                if metadata_out_path.is_file()
                else {}
            )
            geometry = compute_neck_down_crop(
                image_width=image_width,
                image_height=image_height,
                person_mask=person_mask,
                base_crop=base_crop,
                config=resolved_config,
                collarbone_cutoff_y=existing.get("collarbone_cutoff_reference", {}).get(
                    "source_y_px"
                ),
            )
            qc_status = PRIVACY_QC_USER_APPROVED
            qc_notes = [fixture_override.note] if fixture_override.note else []
            payload = serialize_neck_down_metadata(
                fixture_id=fixture_id,
                geometry=geometry,
                source_metadata=source_metadata,
                source_refocused_path=source_variant_path,
                output_path=output_path,
                source_variant=source_variant,
                qc_status=qc_status,
                qc_notes=qc_notes,
                render_mode=existing.get("render_mode", render_mode),
                fixture_override=fixture_override,
            )
            metadata_out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            return NeckDownCandidateResult(
                fixture_id=fixture_id,
                geometry=geometry,
                output_path=str(output_path),
                metadata_path=str(metadata_out_path),
                source_refocused_path=str(source_variant_path),
                source_variant=source_variant,
                output_sha256=sha256_file(output_path),
                generated_or_reused="reused",
                qc_status=qc_status,
                qc_notes=tuple(qc_notes),
            )
        if not force and metadata_out_path.is_file() and output_path.is_file():
            existing = json.loads(metadata_out_path.read_text(encoding="utf-8"))
            if privacy_metadata_reuse_eligible(
                existing,
                source_variant_sha256=source_variant_sha256,
                config=resolved_config,
                source_variant=source_variant,
            ) and existing.get("output_sha256") == sha256_file(output_path):
                geometry = compute_neck_down_crop(
                    image_width=image_width,
                    image_height=image_height,
                    person_mask=person_mask,
                    base_crop=base_crop,
                    config=resolved_config,
                    collarbone_cutoff_y=existing.get("collarbone_cutoff_reference", {}).get(
                        "source_y_px"
                    ),
                )
                qc_status = existing.get("qc", {}).get("status", PRIVACY_QC_PASS)
                qc_notes = tuple(existing.get("qc", {}).get("notes", []))
                return NeckDownCandidateResult(
                    fixture_id=fixture_id,
                    geometry=geometry,
                    output_path=str(output_path),
                    metadata_path=str(metadata_out_path),
                    source_refocused_path=str(source_variant_path),
                    source_variant=source_variant,
                    output_sha256=existing["output_sha256"],
                    generated_or_reused="reused",
                    qc_status=qc_status,
                    qc_notes=qc_notes,
                )

        collarbone_cutoff_y, _ = estimate_collarbone_cutoff_y_from_mask(
            person_mask=person_mask,
            base_crop=base_crop,
            image_height=image_height,
        )
        geometry = compute_neck_down_crop(
            image_width=image_width,
            image_height=image_height,
            person_mask=person_mask,
            base_crop=base_crop,
            config=resolved_config,
            collarbone_cutoff_y=collarbone_cutoff_y,
        )
        qc_status, qc_notes = assess_privacy_qc(
            geometry=geometry,
            person_mask=person_mask,
            base_crop=base_crop,
            source_metadata=source_metadata,
            image_height=image_height,
            source_variant=source_variant,
        )
        if qc_status == PRIVACY_QC_FAIL:
            raise ValueError(f"privacy QC failed for {fixture_id}: {', '.join(qc_notes)}")
        if fixture_override and fixture_override.user_approved:
            qc_status = PRIVACY_QC_USER_APPROVED
            qc_notes = [fixture_override.note] if fixture_override.note else []

        if use_original_source:
            output_image = render_neck_down_from_original(
                source_image.convert("RGB"),
                geometry.neck_down_crop,
            )
        elif prefer_refocused_subcrop:
            with Image.open(source_variant_path) as source_variant_image:
                output_image = render_neck_down_from_refocused(
                    source_variant_image.convert("RGB"),
                    geometry.sub_crop_from_refocused,
                )
        else:
            output_image = render_neck_down_from_source(
                source_image.convert("RGB"),
                person_mask,
                geometry,
            )

    if not (fixture_override and fixture_override.user_approved):
        output_image.save(output_path, quality=92)

    payload = serialize_neck_down_metadata(
        fixture_id=fixture_id,
        geometry=geometry,
        source_metadata=source_metadata,
        source_refocused_path=source_variant_path,
        output_path=output_path,
        source_variant=source_variant,
        qc_status=qc_status,
        qc_notes=qc_notes,
        render_mode=render_mode,
        fixture_override=fixture_override,
    )
    metadata_out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return NeckDownCandidateResult(
        fixture_id=fixture_id,
        geometry=geometry,
        output_path=str(output_path),
        metadata_path=str(metadata_out_path),
        source_refocused_path=str(source_variant_path),
        source_variant=source_variant,
        output_sha256=payload["output_sha256"],
        generated_or_reused="processed",
        qc_status=qc_status,
        qc_notes=tuple(qc_notes),
    )


def process_fixture_privacy_crop(
    fixture_id: str,
    *,
    repo_root: Path,
    candidate_root: Path = DEFAULT_OUTPUT_ROOT,
    overrides: dict[str, Any] | None = None,
    force: bool = False,
) -> NeckDownCandidateResult:
    return generate_neck_down_review_candidate(
        fixture_id=fixture_id,
        repo_root=repo_root,
        candidate_root=candidate_root,
        overrides=overrides,
        force=force,
    )


def process_fixtures_privacy_crop(
    fixture_ids: list[str],
    *,
    repo_root: Path,
    candidate_root: Path = DEFAULT_OUTPUT_ROOT,
    overrides_path: Path | None = None,
    continue_on_error: bool = True,
    force: bool = False,
) -> PrivacyCropBatchResult:
    root = Path(repo_root).expanduser().resolve()
    overrides = load_privacy_cutoff_overrides(root, overrides_path)
    processed: list[str] = []
    reused: list[str] = []
    failed: dict[str, str] = {}
    limitations: dict[str, list[str]] = {}

    for fixture_id in fixture_ids:
        try:
            result = process_fixture_privacy_crop(
                fixture_id,
                repo_root=root,
                candidate_root=candidate_root,
                overrides=overrides,
                force=force,
            )
            if result.generated_or_reused == "reused":
                reused.append(fixture_id)
            else:
                processed.append(fixture_id)
            if result.qc_status == PRIVACY_QC_LIMITATION:
                limitations[fixture_id] = list(result.qc_notes)
        except Exception as exc:
            failed[fixture_id] = str(exc)
            if not continue_on_error:
                raise
    return PrivacyCropBatchResult(
        processed=processed,
        reused=reused,
        failed=failed,
        limitations=limitations,
    )
