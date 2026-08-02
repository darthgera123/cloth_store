"""Generic geometry-reference override for production catalog pipeline.

When a user override specifies ``geometry_reference_override``, the pipeline
substitutes a derived neutral silhouette (or other approved geometry artifact)
for the canonical template and builds a geometry-aware prompt. Input inclusion
is governed by ``input_role_policy`` (e.g. omit detail crop when the reviewed
candidate did not send Image 3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from cloth_store.catalog_derived_geometry import (
    IMAGE_ROLE_DERIVED_GEOMETRY,
    build_geometry_candidate_prompt,
    validate_derived_geometry_image,
    validate_derived_geometry_path,
    validate_geometry_source_path,
)
from cloth_store.catalog_detail_crop import (
    DEFAULT_DETAIL_CROP_ROOT,
    detail_crop_output_path,
    extract_detail_crop,
)
from cloth_store.catalog_paths import DEFAULT_CUTOUT_ROOT, catalog_cutout_path
from cloth_store.catalog_user_override import (
    InputRolePolicy,
    UserOverrideConfig,
)
from cloth_store.catalog_vlm_records import extraction_record_sha256
from cloth_store.gemini_catalog import NANO_BANANA_2_MODEL_ID, RUNNER_MODEL_ID
from cloth_store.gemini_catalog_request import (
    ARTIFACT_VERSION,
    IMAGE_ROLE_GARMENT_DETAIL,
    IMAGE_ROLE_GARMENT_IDENTITY,
    CatalogRequestArtifactError,
    describe_image_input,
    validate_prompt_constraints,
    validate_source_provenance,
)


def _describe_derived_geometry_input(
    *,
    order: int,
    description: str,
    absolute_path: Path,
    repo_root: Path,
    fixture_id: str,
    case_role: str,
) -> dict[str, Any]:
    from cloth_store.gemini_catalog_generate import sha256_file
    from cloth_store.gemini_catalog_request import validate_catalog_image

    dimensions = validate_catalog_image(absolute_path)
    relative = absolute_path.resolve().relative_to(repo_root.resolve()).as_posix()
    validate_derived_geometry_path(relative)
    return {
        "order": order,
        "role": IMAGE_ROLE_DERIVED_GEOMETRY,
        "description": description,
        "path": relative,
        "sha256": sha256_file(absolute_path),
        "width": dimensions["width"],
        "height": dimensions["height"],
        "mode": dimensions["mode"],
    }


def resolve_include_detail_reference(
    *,
    role: str,
    input_role_policy: InputRolePolicy | None,
    detail_result_included: bool,
) -> bool:
    if input_role_policy is not None and input_role_policy.include_detail_reference is not None:
        return input_role_policy.include_detail_reference
    return role == "top" and detail_result_included


def build_geometry_reference_request_artifact(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    template_id: str,
    extraction_record: dict[str, Any],
    user_override: UserOverrideConfig,
    template_selection: dict[str, Any] | None = None,
    cutout_root: Path = DEFAULT_CUTOUT_ROOT,
    detail_root: Path = DEFAULT_DETAIL_CROP_ROOT,
) -> dict[str, Any]:
    geo = user_override.geometry_reference_override
    if geo is None:
        raise CatalogRequestArtifactError(
            "geometry_reference_override required for geometry reference artifact"
        )

    cutout = repo_root / catalog_cutout_path(
        cutout_root=cutout_root,
        fixture_id=fixture_id,
        role=role,
    )
    validate_source_provenance(
        cutout.resolve().relative_to(repo_root.resolve()).as_posix(),
        image_role=IMAGE_ROLE_GARMENT_IDENTITY,
        fixture_id=fixture_id,
        role=role,
    )

    derived_path = repo_root / geo.derived_geometry_path
    if not derived_path.is_file():
        raise CatalogRequestArtifactError(f"derived geometry not found: {derived_path}")
    validate_derived_geometry_path(geo.derived_geometry_path)
    validate_derived_geometry_image(Image.open(derived_path).convert("RGB"))
    if geo.derived_geometry_sha256 is not None:
        from cloth_store.gemini_catalog_generate import sha256_file

        digest = sha256_file(derived_path)
        if digest != geo.derived_geometry_sha256:
            raise CatalogRequestArtifactError(
                f"derived geometry sha256 mismatch: expected {geo.derived_geometry_sha256}, "
                f"got {digest}"
            )

    validate_geometry_source_path(geo.geometry_source_path)

    garment = describe_image_input(
        order=1,
        role=IMAGE_ROLE_GARMENT_IDENTITY,
        description="Plan 1 segmented catalog cutout (identity/color/texture reference)",
        absolute_path=cutout,
        repo_root=repo_root,
        fixture_id=fixture_id,
        case_role=role,
    )
    derived = _describe_derived_geometry_input(
        order=2,
        description=(
            f"Derived neutral geometry silhouette from {geo.geometry_source_fixture} catalog "
            "output (geometry/presentation only; no color or fabric)"
        ),
        absolute_path=derived_path,
        repo_root=repo_root,
        fixture_id=fixture_id,
        case_role=role,
    )

    detail_provenance: dict[str, Any] | None = None
    include_detail = False
    detail_result = None
    if role == "top":
        detail_abs = repo_root / detail_crop_output_path(
            detail_root=detail_root,
            fixture_id=fixture_id,
            role=role,
        )
        detail_result = extract_detail_crop(cutout, output_path=detail_abs)
        include_detail = resolve_include_detail_reference(
            role=role,
            input_role_policy=user_override.input_role_policy,
            detail_result_included=detail_result.included,
        )
        if include_detail and detail_result.output_path is not None:
            detail = describe_image_input(
                order=3,
                role=IMAGE_ROLE_GARMENT_DETAIL,
                description="Source-derived garment detail crop (texture reinforcement only)",
                absolute_path=detail_result.output_path,
                repo_root=repo_root,
                fixture_id=fixture_id,
                case_role=role,
            )
            detail_provenance = {
                "included": True,
                "reason": detail_result.reason,
                "path": detail.repo_relative_path,
                "sha256": detail.sha256,
            }
        else:
            detail_provenance = {
                "included": False,
                "reason": detail_result.reason,
                "path": None,
                "sha256": None,
            }

    attributes = extraction_record["attributes"]
    prompt, injected_fields = build_geometry_candidate_prompt(
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        geometry_source_fixture=geo.geometry_source_fixture,
        attributes=attributes,
        include_detail_reference=include_detail,
    )
    validate_prompt_constraints(prompt)

    images = [
        {
            "order": garment.order,
            "role": garment.role,
            "description": garment.description,
            "path": garment.repo_relative_path,
            "sha256": garment.sha256,
            "width": garment.width,
            "height": garment.height,
            "mode": garment.mode,
        },
        derived,
    ]
    part_order = [IMAGE_ROLE_GARMENT_IDENTITY, IMAGE_ROLE_DERIVED_GEOMETRY]
    if include_detail and detail_result.output_path is not None:
        detail = describe_image_input(
            order=3,
            role=IMAGE_ROLE_GARMENT_DETAIL,
            description="Source-derived garment detail crop (texture reinforcement only)",
            absolute_path=detail_result.output_path,
            repo_root=repo_root,
            fixture_id=fixture_id,
            case_role=role,
        )
        images.append(
            {
                "order": detail.order,
                "role": detail.role,
                "description": detail.description,
                "path": detail.repo_relative_path,
                "sha256": detail.sha256,
                "width": detail.width,
                "height": detail.height,
                "mode": detail.mode,
            }
        )
        part_order.append(IMAGE_ROLE_GARMENT_DETAIL)

    payload: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "bench": "catalog_generation",
        "prompt_policy_version": geo.prompt_policy_version,
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
        "vlm_injected_fields": injected_fields,
        "vlm_attribute_json_sha256": extraction_record_sha256(extraction_record),
        "geometry_reference_override": geo.to_artifact_block(),
        "detail_reference_provenance": detail_provenance,
    }
    if template_selection is not None:
        payload["template_selection"] = template_selection
    override_block = user_override.to_artifact_block(
        injected_high_confidence_fields=injected_fields,
        vlm_attribute_json_sha256=extraction_record_sha256(extraction_record),
        sheen_constraint="",
    )
    if override_block:
        payload["user_override"] = override_block
    return payload


def validate_geometry_reference_request_artifact(
    payload: dict[str, Any],
    *,
    repo_root: Path,
) -> None:
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        raise CatalogRequestArtifactError("unsupported artifact_version")

    case = payload.get("case")
    if not isinstance(case, dict):
        raise CatalogRequestArtifactError("case must be an object")
    fixture_id = case.get("fixture")
    role = case.get("role")
    template_id = payload.get("template_id")
    if (
        not isinstance(fixture_id, str)
        or not isinstance(role, str)
        or not isinstance(template_id, str)
    ):
        raise CatalogRequestArtifactError(
            "case.fixture, case.role, and template_id must be strings"
        )

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise CatalogRequestArtifactError("prompt must be a non-empty string")
    validate_prompt_constraints(prompt)

    images = payload.get("images")
    if not isinstance(images, list) or len(images) not in (2, 3):
        raise CatalogRequestArtifactError("images must contain two or three entries")

    expected_roles = [IMAGE_ROLE_GARMENT_IDENTITY, IMAGE_ROLE_DERIVED_GEOMETRY]
    if len(images) == 3:
        expected_roles.append(IMAGE_ROLE_GARMENT_DETAIL)

    from cloth_store.gemini_catalog_generate import sha256_file
    from cloth_store.gemini_catalog_request import validate_catalog_image

    for index, (record, expected_role) in enumerate(zip(images, expected_roles, strict=True)):
        if record.get("role") != expected_role:
            raise CatalogRequestArtifactError(
                f"images[{index}].role must be {expected_role!r}, got {record.get('role')!r}"
            )
        relative = record.get("path")
        if not isinstance(relative, str):
            raise CatalogRequestArtifactError(f"images[{index}].path must be a string")

        if expected_role == IMAGE_ROLE_DERIVED_GEOMETRY:
            validate_derived_geometry_path(relative)
        elif expected_role == IMAGE_ROLE_GARMENT_IDENTITY:
            validate_source_provenance(
                relative,
                image_role=expected_role,
                fixture_id=fixture_id,
                role=role,
            )
        else:
            validate_source_provenance(
                relative,
                image_role=expected_role,
                fixture_id=fixture_id,
                role=role,
            )

        absolute = repo_root / relative
        dimensions = validate_catalog_image(absolute)
        digest = sha256_file(absolute)
        if record.get("sha256") != digest:
            raise CatalogRequestArtifactError(f"images[{index}] sha256 mismatch for {relative}")
        if (
            record.get("width") != dimensions["width"]
            or record.get("height") != dimensions["height"]
        ):
            raise CatalogRequestArtifactError(f"images[{index}] dimensions mismatch for {relative}")
