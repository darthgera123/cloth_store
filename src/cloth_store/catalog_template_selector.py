"""Deterministic catalog template selection from normalized garment attributes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_GARMENT_ATTRIBUTES = Path("bench/plan1_localization/garment_attributes.json")

OFFICE_GARMENT_CLASSES = frozenset({"office_blouse", "office_shirt", "office_top"})
BLAZER_GARMENT_CLASSES = frozenset({"blazer", "suit_jacket", "jacket"})
WAISTCOAT_GARMENT_CLASSES = frozenset({"waistcoat", "vest"})
BLOUSE_GARMENT_CLASSES = frozenset({"blouse", "shirt", "top", *OFFICE_GARMENT_CLASSES})
DRESS_GARMENT_CLASSES = frozenset({"dress"})
PANTS_GARMENT_CLASSES = frozenset({"trousers", "pants", "jeans"})
SKIRT_GARMENT_CLASSES = frozenset({"skirt"})

FULL_SLEEVE_VALUES = frozenset({"full", "long", "long_sleeve"})
HALF_SLEEVE_VALUES = frozenset({"half", "short", "short_sleeve"})
SLEEVELESS_SLEEVE_VALUES = frozenset({"sleeveless", "none", "no_sleeve", "no_sleeves"})
PENCIL_SKIRT_VALUES = frozenset({"pencil", "straight", "pencil_skirt"})
A_LINE_SKIRT_VALUES = frozenset({"a_line", "flared", "a-line"})
KNEE_LENGTH_SKIRT_VALUES = frozenset(
    {"knee_length", "knee", "midi", "knee_length_skirt", "knee_skirt"}
)
LONG_SKIRT_VALUES = frozenset(
    {"long", "maxi", "floor", "ankle", "long_skirt", "maxi_skirt", "full_length"}
)


@dataclass(frozen=True)
class GarmentAttributes:
    fixture: str
    role: str
    garment_class: str
    sleeve_length: str | None
    skirt_style: str | None
    source_evidence: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> GarmentAttributes:
        return cls(
            fixture=str(record["fixture"]),
            role=str(record["role"]),
            garment_class=str(record["garment_class"]).strip().lower(),
            sleeve_length=(
                str(record["sleeve_length"]).strip().lower()
                if record.get("sleeve_length") not in (None, "")
                else None
            ),
            skirt_style=(
                str(record["skirt_style"]).strip().lower()
                if record.get("skirt_style") not in (None, "")
                else None
            ),
            source_evidence=str(record.get("source_evidence", "")),
        )


@dataclass(frozen=True)
class TemplateSelection:
    template_id: str
    confidence: str
    reason: str
    garment_class_normalized: str
    sleeve_length_normalized: str | None
    skirt_style_normalized: str | None
    override_applied: bool = False
    selector: str = "catalog_template_selector_v1"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "confidence": self.confidence,
            "reason": self.reason,
            "garment_class_normalized": self.garment_class_normalized,
            "sleeve_length_normalized": self.sleeve_length_normalized,
            "skirt_style_normalized": self.skirt_style_normalized,
            "override_applied": self.override_applied,
            "selector": self.selector,
        }


def load_garment_attributes(
    path: Path | str = DEFAULT_GARMENT_ATTRIBUTES,
) -> list[GarmentAttributes]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [GarmentAttributes.from_record(record) for record in payload["cases"]]


def garment_attributes_for_case(
    attributes: list[GarmentAttributes],
    *,
    fixture: str,
    role: str,
) -> GarmentAttributes | None:
    for record in attributes:
        if record.fixture == fixture and record.role == role:
            return record
    return None


def normalize_garment_class(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "suit_jacket": "blazer",
        "jacket": "blazer",
        "office_top": "office_blouse",
        "office_shirt": "office_blouse",
        "jeans": "trousers",
        "pants": "trousers",
        "straight_skirt": "skirt",
        "pencil_skirt": "skirt",
        "vest": "waistcoat",
    }
    return aliases.get(normalized, normalized)


def normalize_sleeve_length(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in FULL_SLEEVE_VALUES:
        return "full"
    if normalized in HALF_SLEEVE_VALUES:
        return "half"
    if normalized in SLEEVELESS_SLEEVE_VALUES:
        return "sleeveless"
    return None


def normalize_skirt_style(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in PENCIL_SKIRT_VALUES:
        return "pencil"
    if normalized in KNEE_LENGTH_SKIRT_VALUES:
        return "knee_length"
    if normalized in LONG_SKIRT_VALUES:
        return "long"
    if normalized in A_LINE_SKIRT_VALUES:
        return "a_line"
    return normalized


def select_template_from_attributes(
    attributes: GarmentAttributes,
    *,
    template_override: str | None = None,
) -> TemplateSelection:
    garment_class = normalize_garment_class(attributes.garment_class)
    sleeve = normalize_sleeve_length(attributes.sleeve_length)
    skirt_style = normalize_skirt_style(attributes.skirt_style)

    if template_override:
        return TemplateSelection(
            template_id=template_override,
            confidence="high",
            reason=f"Explicit reviewed override to {template_override!r}.",
            garment_class_normalized=garment_class,
            sleeve_length_normalized=sleeve,
            skirt_style_normalized=skirt_style,
            override_applied=True,
        )

    if attributes.role == "dress":
        return _select_dress_template(
            garment_class=garment_class,
            sleeve=sleeve,
            skirt_style=skirt_style,
            source_evidence=attributes.source_evidence,
        )
    if attributes.role == "top":
        return _select_top_template(
            garment_class=garment_class,
            sleeve=sleeve,
            skirt_style=skirt_style,
            source_evidence=attributes.source_evidence,
        )
    if attributes.role == "bottom":
        return _select_bottom_template(
            garment_class=garment_class,
            skirt_style=skirt_style,
            source_evidence=attributes.source_evidence,
        )
    raise ValueError(f"unsupported role for template selection: {attributes.role!r}")


def _select_dress_template(
    *,
    garment_class: str,
    sleeve: str | None,
    skirt_style: str | None,
    source_evidence: str,
) -> TemplateSelection:
    if garment_class not in DRESS_GARMENT_CLASSES:
        return TemplateSelection(
            template_id="dress_knee_length_half_sleeve",
            confidence="low",
            reason=(
                f"Role dress with unexpected garment class {garment_class!r}; "
                f"defaulting to dress_knee_length_half_sleeve pending review. "
                f"Evidence: {source_evidence}"
            ),
            garment_class_normalized=garment_class,
            sleeve_length_normalized=sleeve,
            skirt_style_normalized=skirt_style,
        )

    if sleeve == "half" and skirt_style == "knee_length":
        template_id = "dress_knee_length_half_sleeve"
        reason = (
            f"One-piece knee-length dress with half sleeves mapped to "
            f"dress_knee_length_half_sleeve. Evidence: {source_evidence}"
        )
        confidence = "high"
    elif sleeve == "full" and skirt_style == "knee_length":
        template_id = "dress_knee_length_full_sleeve"
        reason = (
            f"One-piece knee-length dress with full sleeves mapped to "
            f"dress_knee_length_full_sleeve. Evidence: {source_evidence}"
        )
        confidence = "high"
    elif sleeve == "half":
        template_id = "dress_knee_length_half_sleeve"
        reason = (
            f"One-piece dress with half sleeves; default knee-length dress template. "
            f"Evidence: {source_evidence}"
        )
        confidence = "high" if skirt_style == "knee_length" else "low"
    elif sleeve == "full":
        template_id = "dress_knee_length_full_sleeve"
        reason = (
            f"One-piece dress with full sleeves mapped to dress_knee_length_full_sleeve. "
            f"Evidence: {source_evidence}"
        )
        confidence = "high" if skirt_style == "knee_length" else "low"
    else:
        template_id = "dress_knee_length_half_sleeve"
        reason = (
            f"Dress class without supported sleeve length; default knee-length dress "
            f"template pending reviewed override. Evidence: {source_evidence}"
        )
        confidence = "low"
    return TemplateSelection(
        template_id=template_id,
        confidence=confidence,
        reason=reason,
        garment_class_normalized=garment_class,
        sleeve_length_normalized=sleeve,
        skirt_style_normalized=skirt_style,
    )


def _select_top_template(
    *,
    garment_class: str,
    sleeve: str | None,
    skirt_style: str | None,
    source_evidence: str,
) -> TemplateSelection:
    if garment_class in BLAZER_GARMENT_CLASSES:
        return TemplateSelection(
            template_id="blazer",
            confidence="high" if sleeve == "full" else "low",
            reason=f"Blazer/suit jacket class mapped to blazer. Evidence: {source_evidence}",
            garment_class_normalized=garment_class,
            sleeve_length_normalized=sleeve,
            skirt_style_normalized=None,
        )

    if garment_class in WAISTCOAT_GARMENT_CLASSES:
        return TemplateSelection(
            template_id="waistcoat_closed",
            confidence="high",
            reason=(
                f"Waistcoat/vest class mapped to waistcoat_closed. Evidence: {source_evidence}"
            ),
            garment_class_normalized=garment_class,
            sleeve_length_normalized=sleeve,
            skirt_style_normalized=None,
        )

    if garment_class in BLOUSE_GARMENT_CLASSES:
        if sleeve == "full":
            template_id = "top_full_sleeve"
            reason = f"Generic blouse/shirt with {sleeve} sleeves. Evidence: {source_evidence}"
        elif sleeve == "half":
            template_id = "top_half_sleeve"
            reason = f"Generic blouse/shirt with {sleeve} sleeves. Evidence: {source_evidence}"
        elif sleeve == "sleeveless":
            template_id = "top_sleeveless"
            reason = (
                f"Sleeveless blouse/shirt/top mapped to top_sleeveless. Evidence: {source_evidence}"
            )
        else:
            return TemplateSelection(
                template_id="top_full_sleeve",
                confidence="low",
                reason=(
                    "Blouse/shirt class without a supported sleeve length; requires explicit "
                    f"reviewed override. Evidence: {source_evidence}"
                ),
                garment_class_normalized=garment_class,
                sleeve_length_normalized=sleeve,
                skirt_style_normalized=None,
            )
        return TemplateSelection(
            template_id=template_id,
            confidence="high",
            reason=reason,
            garment_class_normalized=garment_class,
            sleeve_length_normalized=sleeve,
            skirt_style_normalized=None,
        )

    return TemplateSelection(
        template_id="top_full_sleeve",
        confidence="low",
        reason=(
            f"Unsupported top garment class {garment_class!r}; fallback to top_full_sleeve "
            f"pending reviewed override. Evidence: {source_evidence}"
        ),
        garment_class_normalized=garment_class,
        sleeve_length_normalized=sleeve,
        skirt_style_normalized=None,
    )


def _select_bottom_template(
    *,
    garment_class: str,
    skirt_style: str | None,
    source_evidence: str,
) -> TemplateSelection:
    if garment_class in PANTS_GARMENT_CLASSES:
        return TemplateSelection(
            template_id="pants",
            confidence="high",
            reason=f"Trousers/pants class. Evidence: {source_evidence}",
            garment_class_normalized=garment_class,
            sleeve_length_normalized=None,
            skirt_style_normalized=skirt_style,
        )

    if garment_class in SKIRT_GARMENT_CLASSES or skirt_style is not None:
        if skirt_style == "pencil":
            template_id = "skirt_pencil"
            confidence = "high"
            reason = f"Pencil/straight skirt style. Evidence: {source_evidence}"
        elif skirt_style == "knee_length":
            template_id = "skirt_knee_length"
            confidence = "high"
            reason = f"Knee-length/midi skirt style. Evidence: {source_evidence}"
        elif skirt_style == "long":
            template_id = "skirt_long"
            confidence = "high"
            reason = f"Long/maxi skirt style. Evidence: {source_evidence}"
        elif skirt_style == "a_line":
            template_id = "skirt"
            confidence = "high"
            reason = f"A-line/flared skirt style. Evidence: {source_evidence}"
        elif skirt_style is None:
            template_id = "skirt"
            confidence = "low"
            reason = (
                "Skirt class without pencil/A-line subtype; defaulting to A-line skirt pending "
                f"reviewed override. Evidence: {source_evidence}"
            )
        else:
            template_id = "skirt"
            confidence = "low"
            reason = (
                f"Unsupported skirt style {skirt_style!r}; defaulting to skirt pending override. "
                f"Evidence: {source_evidence}"
            )
        return TemplateSelection(
            template_id=template_id,
            confidence=confidence,
            reason=reason,
            garment_class_normalized=garment_class,
            sleeve_length_normalized=None,
            skirt_style_normalized=skirt_style,
        )

    return TemplateSelection(
        template_id="pants",
        confidence="low",
        reason=(
            f"Unsupported bottom garment class {garment_class!r}; fallback to pants pending "
            f"reviewed override. Evidence: {source_evidence}"
        ),
        garment_class_normalized=garment_class,
        sleeve_length_normalized=None,
        skirt_style_normalized=skirt_style,
    )


def validate_manifest_case_against_selector(
    case: dict[str, Any],
    attributes: GarmentAttributes,
) -> dict[str, Any] | None:
    override = case.get("template_override")
    selection = select_template_from_attributes(attributes, template_override=override)
    expected_template = case.get("template_id")
    expected_confidence = case.get("confidence")
    if selection.template_id != expected_template or selection.confidence != expected_confidence:
        return {
            "fixture": case["fixture"],
            "role": case["role"],
            "manifest_template_id": expected_template,
            "selector_template_id": selection.template_id,
            "manifest_confidence": expected_confidence,
            "selector_confidence": selection.confidence,
            "selector_reason": selection.reason,
            "override_applied": selection.override_applied,
        }
    return None


def validate_all_manifest_cases(
    manifest: dict[str, Any],
    *,
    attributes_path: Path | str = DEFAULT_GARMENT_ATTRIBUTES,
) -> list[dict[str, Any]]:
    attributes = load_garment_attributes(attributes_path)
    discrepancies: list[dict[str, Any]] = []
    for case in manifest.get("cases", []):
        record = garment_attributes_for_case(
            attributes,
            fixture=str(case["fixture"]),
            role=str(case["role"]),
        )
        if record is None:
            discrepancies.append(
                {
                    "fixture": case["fixture"],
                    "role": case["role"],
                    "error": "missing garment_attributes record",
                }
            )
            continue
        mismatch = validate_manifest_case_against_selector(case, record)
        if mismatch is not None:
            discrepancies.append(mismatch)
    return discrepancies
