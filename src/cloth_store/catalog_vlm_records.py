"""VLM attribute record loading and prompt clause builders for production."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cloth_store.gemini_catalog_generate import sha256_text
from cloth_store.gemini_catalog_request import (
    CatalogRequestArtifactError,
    build_catalog_generation_prompt,
    validate_prompt_constraints,
)
from cloth_store.vlm_garment_attributes import serialize_extraction_record

_SHEEN_FORBIDDEN = (
    "glossy",
    "metallic",
    "vinyl",
    "plastic",
    "lacquer",
    "mirror-like",
    "wet-look",
)

_ATTRIBUTE_INJECTION_ORDER: tuple[str, ...] = (
    "dominant_color",
    "likely_material",
    "surface_sheen",
    "texture_pattern",
    "weave_finish",
    "closures_details",
    "sleeve_cuff_neckline",
    "garment_class",
)


def load_extraction_record(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def extraction_record_sha256(record: dict[str, Any]) -> str:
    return sha256_text(serialize_extraction_record(record))


def format_attribute_injection_line(name: str, field: dict[str, str]) -> str:
    label = name.replace("_", " ")
    kind = field["observation_type"]
    return (
        f"- {label}: {field['value']} ({field['confidence']} confidence, {kind}; "
        f"{field['evidence']})"
    )


def _format_forbidden_sheen() -> str:
    return ", ".join(_SHEEN_FORBIDDEN[:-1]) + f", or {_SHEEN_FORBIDDEN[-1]}"


def build_sheen_constraint(field: dict[str, str] | None) -> str:
    if field is None:
        return (
            "Preserve the source-visible reflectivity from Image 1. Do not exaggerate sheen to "
            "glossy, metallic, vinyl, or plastic finishes."
        )

    value_lower = field["value"].lower()
    if any(term in value_lower for term in ("matte", "low sheen", "no sheen", "dull")):
        return (
            f"Image 1 shows {field['value']}. Keep this low reflectivity. Do not add satin, "
            f"gloss, metallic, vinyl, or plastic shine absent from Image 1."
        )

    if any(
        term in value_lower for term in ("glossy", "high sheen", "lustrous", "specular", "satin")
    ):
        return (
            "Image 1 shows lustrous satin-like reflectivity with soft diffused highlights. "
            "Preserve that subtle satin sheen exactly as visible in Image 1. "
            f"Do NOT exaggerate beyond the source to {_format_forbidden_sheen()} finishes."
        )

    return (
        f"Image 1 shows {field['value']}. Preserve this soft, subtle satin-like reflectivity "
        f"where visible. Do NOT exaggerate to {_format_forbidden_sheen()} finishes."
    )


def build_vlm_attribute_clause(
    attributes: dict[str, dict[str, str]],
) -> tuple[str, list[str]]:
    injected: list[str] = []
    lines: list[str] = []

    sheen_field = attributes.get("surface_sheen")
    if sheen_field and sheen_field["confidence"] == "high":
        injected.append("surface_sheen")
        lines.append(format_attribute_injection_line("surface_sheen", sheen_field))

    for name in _ATTRIBUTE_INJECTION_ORDER:
        if name == "surface_sheen":
            continue
        field = attributes.get(name)
        if field is None or field["confidence"] != "high":
            continue
        injected.append(name)
        lines.append(format_attribute_injection_line(name, field))

    sheen_constraint = build_sheen_constraint(
        sheen_field if sheen_field and sheen_field["confidence"] == "high" else None
    )

    if not lines:
        clause = (
            "VLM-derived material cues (supplement Image 1; do not override visible source):\n"
            f"{sheen_constraint}\n"
            "Image 1 remains authoritative for all appearance details."
        )
        return clause, injected

    body = "\n".join(lines)
    clause = (
        "VLM-derived material cues (supplement Image 1; do not override visible source):\n"
        f"{body}\n\n"
        f"Sheen constraint: {sheen_constraint}\n"
        "These cues clarify Image 1; they must not override pixels visible in Image 1 or Image 3."
    )
    return clause, injected


def build_vlm_conditioned_prompt(
    *,
    fixture_id: str,
    role: str,
    template_id: str,
    attributes: dict[str, dict[str, str]],
    include_detail_reference: bool = False,
) -> tuple[str, list[str]]:
    base = build_catalog_generation_prompt(
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        include_detail_reference=include_detail_reference,
    )
    clause, injected = build_vlm_attribute_clause(attributes)

    marker = "Image 1 is authoritative for visible color, material, and weave."
    if marker not in base:
        raise CatalogRequestArtifactError(
            "base catalog prompt missing universal tail marker for VLM injection"
        )

    prompt = base.replace(
        marker,
        f"{clause}\n\n{marker}",
        1,
    )
    validate_prompt_constraints(prompt)
    return prompt, injected
