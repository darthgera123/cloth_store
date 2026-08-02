"""User-corrected request artifact builder for production pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cloth_store.catalog_detail_crop import (
    DEFAULT_DETAIL_CROP_ROOT,
    detail_crop_output_path,
    extract_detail_crop,
)
from cloth_store.catalog_paths import DEFAULT_CUTOUT_ROOT, DEFAULT_TEMPLATE_ROOT
from cloth_store.catalog_user_override import UserOverrideConfig, build_user_override_clause
from cloth_store.catalog_vlm_records import (
    build_sheen_constraint,
    build_vlm_attribute_clause,
    extraction_record_sha256,
)
from cloth_store.gemini_catalog import NANO_BANANA_2_MODEL_ID, RUNNER_MODEL_ID
from cloth_store.gemini_catalog_request import (
    ARTIFACT_VERSION,
    IMAGE_ROLE_GARMENT_DETAIL,
    IMAGE_ROLE_GARMENT_IDENTITY,
    IMAGE_ROLE_TEMPLATE_GEOMETRY,
    CatalogRequestArtifactError,
    build_catalog_generation_prompt,
    describe_image_input,
    resolve_case_image_paths,
    validate_prompt_constraints,
)

USER_CORRECTED_SHIRT_NAMESPACE = "user_corrected_shirt_v1"
USER_CORRECTED_PROMPT_POLICY_VERSION = 6

USER_OVERRIDE_GARMENT_CLASS = "shirt"
USER_OVERRIDE_REASON = (
    "User correction: garment is a shirt with structured collar and front placket, "
    "not a round-neck or collarless top."
)

_PROHIBITED_NECKLINE_CONVERSIONS: tuple[str, ...] = (
    "crew neck",
    "round neck",
    "T-shirt",
    "collarless blouse",
    "simplified neckline",
    "mock neck",
    "collarless top",
)

_USER_OVERRIDE_VLM_FIELDS: frozenset[str] = frozenset({"garment_class", "sleeve_cuff_neckline"})

_DEFAULT_OUTFIT_6_PROMPT_LINES: tuple[str, ...] = (
    "Garment class: shirt. This is a structured shirt, NOT a round-neck, collarless, "
    "or simplified-neckline top.",
    "Preserve a shirt collar with structured neckline, front placket, visible buttons, "
    "cuffs, and seams wherever clearly supported by Image 1 or Image 3.",
    "Do NOT convert to: crew neck, round neck, T-shirt, collarless blouse, "
    "simplified neckline, mock neck, collarless top.",
    "Closed, symmetric, front-facing lay-flat catalog presentation.",
    "Preserve deep-red color and soft restrained satin-like sheen from Image 1. "
    "Do not exaggerate to glossy, metallic, vinyl, or plastic finishes.",
    "Do not invent buttons, hardware, or details absent from Image 1 or Image 3.",
)

DEFAULT_OUTFIT_6_OVERRIDE = UserOverrideConfig(
    schema_version=1,
    fixture="outfit_6",
    role="top",
    garment_class=USER_OVERRIDE_GARMENT_CLASS,
    reason=USER_OVERRIDE_REASON,
    overridden_vlm_fields=_USER_OVERRIDE_VLM_FIELDS,
    prohibited_conversions=_PROHIBITED_NECKLINE_CONVERSIONS,
    presentation_requirements=(),
    prompt_lines=_DEFAULT_OUTFIT_6_PROMPT_LINES,
    presentation_mode="text_only",
    precedence="user_override > high_confidence_source_vlm > template_geometry_only",
    namespace=USER_CORRECTED_SHIRT_NAMESPACE,
    template_override=None,
    sheen_constraint=None,
    geometry_reference_override=None,
    input_role_policy=None,
)


def build_user_corrected_vlm_clause(
    attributes: dict[str, dict[str, str]],
    *,
    overridden_fields: frozenset[str],
) -> tuple[str, list[str]]:
    filtered = {name: field for name, field in attributes.items() if name not in overridden_fields}
    clause, injected = build_vlm_attribute_clause(filtered)
    injected = [name for name in injected if name not in overridden_fields]
    return clause, injected


def build_user_corrected_prompt(
    *,
    fixture_id: str,
    role: str,
    template_id: str,
    attributes: dict[str, dict[str, str]],
    user_override: UserOverrideConfig,
    include_detail_reference: bool = False,
) -> tuple[str, list[str]]:
    base = build_catalog_generation_prompt(
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        include_detail_reference=include_detail_reference,
    )
    override_clause = build_user_override_clause(user_override)
    vlm_clause, injected = build_user_corrected_vlm_clause(
        attributes,
        overridden_fields=user_override.overridden_vlm_fields,
    )

    marker = "Image 1 is authoritative for visible color, material, and weave."
    if marker not in base:
        raise CatalogRequestArtifactError(
            "base catalog prompt missing universal tail marker for user override injection"
        )

    prompt = base.replace(
        marker,
        f"{override_clause}\n\n{vlm_clause}\n\n{marker}",
        1,
    )
    validate_prompt_constraints(prompt)
    return prompt, injected


def _image_record(resolved: Any) -> dict[str, Any]:
    return {
        "order": resolved.order,
        "role": resolved.role,
        "description": resolved.description,
        "path": resolved.repo_relative_path,
        "sha256": resolved.sha256,
        "width": resolved.width,
        "height": resolved.height,
        "mode": resolved.mode,
    }


def build_user_corrected_request_artifact(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    template_id: str,
    extraction_record: dict[str, Any],
    user_override: UserOverrideConfig | None = None,
    cutout_root: Path = DEFAULT_CUTOUT_ROOT,
    template_root: Path = DEFAULT_TEMPLATE_ROOT,
    detail_root: Path = DEFAULT_DETAIL_CROP_ROOT,
) -> dict[str, Any]:
    override = user_override or DEFAULT_OUTFIT_6_OVERRIDE
    cutout_path, template_path = resolve_case_image_paths(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        cutout_root=cutout_root,
        template_root=template_root,
    )

    garment = describe_image_input(
        order=1,
        role=IMAGE_ROLE_GARMENT_IDENTITY,
        description="Plan 1 segmented catalog cutout (identity/color/texture reference)",
        absolute_path=cutout_path,
        repo_root=repo_root,
        fixture_id=fixture_id,
        case_role=role,
    )
    template = describe_image_input(
        order=2,
        role=IMAGE_ROLE_TEMPLATE_GEOMETRY,
        description="Canonical template silhouette (geometry/layout reference)",
        absolute_path=template_path,
        repo_root=repo_root,
        fixture_id=fixture_id,
        case_role=role,
        template_id=template_id,
    )

    detail_result = None
    if role == "top":
        detail_abs = repo_root / detail_crop_output_path(
            detail_root=detail_root,
            fixture_id=fixture_id,
            role=role,
        )
        detail_result = extract_detail_crop(cutout_path, output_path=detail_abs)

    include_detail = detail_result is not None and detail_result.included
    attributes = extraction_record["attributes"]
    prompt, injected_fields = build_user_corrected_prompt(
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        attributes=attributes,
        user_override=override,
        include_detail_reference=include_detail,
    )

    images: list[dict[str, Any]] = [
        _image_record(garment),
        _image_record(template),
    ]
    part_order = [IMAGE_ROLE_GARMENT_IDENTITY, IMAGE_ROLE_TEMPLATE_GEOMETRY]
    detail_provenance: dict[str, Any] | None = None

    if include_detail and detail_result is not None and detail_result.output_path is not None:
        detail = describe_image_input(
            order=3,
            role=IMAGE_ROLE_GARMENT_DETAIL,
            description=(
                "Source-derived garment detail crop (texture/pattern/trim reinforcement only)"
            ),
            absolute_path=detail_result.output_path,
            repo_root=repo_root,
            fixture_id=fixture_id,
            case_role=role,
        )
        images.append(_image_record(detail))
        part_order.append(IMAGE_ROLE_GARMENT_DETAIL)
        detail_provenance = {
            "included": True,
            "reason": detail_result.reason,
            "source_bbox": detail_result.source_bbox,
            "crop_bbox": detail_result.crop_bbox,
        }
    elif role == "top" and detail_result is not None:
        detail_provenance = {
            "included": False,
            "reason": detail_result.reason,
            "source_bbox": detail_result.source_bbox,
            "crop_bbox": detail_result.crop_bbox,
        }

    record_hash = extraction_record_sha256(extraction_record)
    sheen_field = attributes.get("surface_sheen")
    sheen_constraint = build_sheen_constraint(
        sheen_field if sheen_field and sheen_field["confidence"] == "high" else None
    )
    payload: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "bench": "catalog_generation",
        "prompt_policy_version": USER_CORRECTED_PROMPT_POLICY_VERSION,
        "runner_model_id": RUNNER_MODEL_ID,
        "gemini_model_id": NANO_BANANA_2_MODEL_ID,
        "case": {"fixture": fixture_id, "role": role},
        "template_id": template_id,
        "prompt": prompt,
        "images": images,
        "request_layout": {
            "separate_parts": True,
            "no_composite_input": True,
            "part_order": part_order,
        },
        "user_override": override.to_artifact_block(
            injected_high_confidence_fields=injected_fields,
            vlm_attribute_json_sha256=record_hash,
            sheen_constraint=sheen_constraint,
        ),
    }
    if detail_provenance is not None:
        payload["detail_reference_provenance"] = detail_provenance
    return payload
