"""Production catalog generation pipeline orchestrator.

Single supported path from segmented garment cutout to final catalog asset:
validate provenance → VLM attributes → optional user override → template selection →
deterministic request artifact → one 1K Gemini call (or hash reuse) → local 512 derivative → QC.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from cloth_store.catalog_detail_crop import (
    DEFAULT_DETAIL_CROP_ROOT,
    detail_crop_output_path,
    extract_detail_crop,
)
from cloth_store.catalog_garment_identities import (
    IdentityAliasTarget,
    default_registry_path,
    lookup_identity_alias,
)
from cloth_store.catalog_geometry_reference import (
    build_geometry_reference_request_artifact,
    validate_geometry_reference_request_artifact,
)
from cloth_store.catalog_output_contract import (
    CANONICAL_COST_1K_USD,
    CANONICAL_IMAGE_SIZE,
    CanonicalOutputPaths,
    production_policy,
    validate_canonical_outputs,
)
from cloth_store.catalog_paths import (
    DEFAULT_CATALOG_MANIFEST,
    DEFAULT_CUTOUT_ROOT,
    catalog_cutout_path,
    catalog_id,
    iter_cases,
    load_manifest,
    manifest_case_for,
    manifest_role_hint,
    resolve_plan1_fixtures,
)
from cloth_store.catalog_request_overrides import build_user_corrected_request_artifact
from cloth_store.catalog_template_selector import (
    DEFAULT_GARMENT_ATTRIBUTES,
    GarmentAttributes,
    TemplateSelection,
    garment_attributes_for_case,
    load_garment_attributes,
    normalize_sleeve_length,
    select_template_from_attributes,
)
from cloth_store.catalog_texture_qc import compare_texture_heuristic
from cloth_store.catalog_user_override import (
    UserOverrideConfig,
    UserOverrideError,
    build_user_override_clause,
    default_override_path,
    load_user_override,
)
from cloth_store.catalog_vlm_records import extraction_record_sha256, load_extraction_record
from cloth_store.gemini_catalog import (
    NANO_BANANA_2_MODEL_ID,
    RUNNER_MODEL_ID,
    GeminiCatalogConfig,
    build_gemini_client,
)
from cloth_store.gemini_catalog_generate import (
    DEFAULT_OUTPUT_ROOT,
    CatalogGenerationError,
    build_generation_contents,
    build_run_metadata,
    extract_response_images,
    generation_request_settings,
    load_existing_result_metadata,
    metadata_matches_artifact,
    normalize_catalog_output,
    repo_relative_path,
    sanitize_api_error,
    serialize_run_metadata,
    sha256_file,
    sha256_text,
)
from cloth_store.gemini_catalog_request import (
    DEFAULT_ARTIFACT_ROOT,
    CatalogRequestArtifactError,
    build_request_artifact,
    validate_request_artifact,
    write_request_artifact,
)

PRODUCTION_NAMESPACE = "catalog_production_v1"
REFERENCE_NAMESPACE = "user_corrected_shirt_v1"
PIPELINE_GENERATION_MODE = "catalog_pipeline"
PIPELINE_METADATA_SCHEMA_VERSION = 1
DEFAULT_VLM_ATTRIBUTES_ROOT = Path("bench/catalog_generation/vlm_attributes")
CANONICAL_COST_NOTE = (
    "Image output pricing only at $0.067 per successful native 1K call; input/thinking excluded."
)

_CONTAMINATED_DETAIL_REASONS = frozenset(
    {
        "insufficient_garment_pixels",
        "garment_area_too_small",
        "crop_too_small",
        "low_garment_pixel_ratio",
    }
)


class CatalogPipelineError(RuntimeError):
    """Raised when the production pipeline cannot proceed safely."""


@dataclass(frozen=True)
class PipelineOutputPaths:
    raw_1k_path: Path
    catalog_512_path: Path
    metadata_path: Path
    artifact_path: Path

    def canonical_paths(self) -> CanonicalOutputPaths:
        return CanonicalOutputPaths(
            raw_1k_path=self.raw_1k_path,
            catalog_512_path=self.catalog_512_path,
            metadata_path=self.metadata_path,
        )


@dataclass(frozen=True)
class PipelinePlan:
    fixture_id: str
    role: str
    template_id: str
    template_selection: TemplateSelection
    artifact: dict[str, Any]
    artifact_rel: str
    output_paths: PipelineOutputPaths
    vlm_record_sha256: str | None
    override_applied: bool
    review_required: bool
    reuse_status: str
    billable: bool
    estimated_cost_usd: float
    reference_promotion: str | None


@dataclass(frozen=True)
class PipelineResult:
    plan: PipelinePlan
    metadata: dict[str, Any] | None
    status: str
    generation_calls: int
    error: str | None = None


def production_case_dir(
    *,
    output_root: Path,
    fixture_id: str,
    namespace: str = PRODUCTION_NAMESPACE,
) -> Path:
    return output_root / RUNNER_MODEL_ID / namespace / fixture_id


def production_output_paths(
    *,
    case_dir: Path,
    role: str,
    artifact_path: Path,
) -> PipelineOutputPaths:
    return PipelineOutputPaths(
        raw_1k_path=case_dir / f"{role}_1k_raw.png",
        catalog_512_path=case_dir / f"{role}.png",
        metadata_path=case_dir / f"{role}.run.json",
        artifact_path=artifact_path,
    )


def default_vlm_attributes_path(
    *,
    vlm_root: Path = DEFAULT_VLM_ATTRIBUTES_ROOT,
    fixture_id: str,
    role: str,
) -> Path:
    return vlm_root / f"{fixture_id}_{role}.attributes.json"


def infer_sleeve_from_vlm_text(value: str) -> str | None:
    lowered = value.lower()
    if any(
        term in lowered
        for term in ("sleeveless", "no sleeves", "no sleeve", "without sleeves", "armholes")
    ):
        return "sleeveless"
    if any(term in lowered for term in ("full sleeve", "long sleeve", "long-sleeve", "wrist")):
        return "full"
    if any(
        term in lowered for term in ("half sleeve", "short sleeve", "short-sleeve", "mid-upper")
    ):
        return "half"
    return normalize_sleeve_length(lowered)


def garment_attributes_from_vlm(
    *,
    fixture_id: str,
    role: str,
    vlm_attributes: dict[str, dict[str, str]] | None,
    user_override: UserOverrideConfig | None,
    reviewed_record: GarmentAttributes | None,
) -> GarmentAttributes:
    if user_override is not None:
        garment_class = user_override.garment_class
    elif vlm_attributes and "garment_class" in vlm_attributes:
        garment_class = vlm_attributes["garment_class"]["value"]
    elif reviewed_record is not None:
        garment_class = reviewed_record.garment_class
    else:
        garment_class = "unknown"

    sleeve_length: str | None = None
    skirt_style: str | None = None
    evidence_parts: list[str] = []

    if user_override is not None and "sleeve_cuff_neckline" in user_override.overridden_vlm_fields:
        inferred = infer_sleeve_from_vlm_text(build_user_override_clause(user_override))
        if inferred is not None:
            sleeve_length = inferred
        elif user_override.template_override == "top_sleeveless":
            sleeve_length = "sleeveless"
        evidence_parts.append(user_override.reason)
    elif vlm_attributes and "sleeve_cuff_neckline" in vlm_attributes:
        sleeve_field = vlm_attributes["sleeve_cuff_neckline"]
        sleeve_length = infer_sleeve_from_vlm_text(sleeve_field["value"])
        evidence_parts.append(sleeve_field["evidence"])

    if reviewed_record is not None:
        if sleeve_length is None:
            sleeve_length = reviewed_record.sleeve_length
        skirt_style = reviewed_record.skirt_style
        if reviewed_record.source_evidence:
            evidence_parts.append(reviewed_record.source_evidence)

    if vlm_attributes and "garment_class" in vlm_attributes and user_override is None:
        evidence_parts.append(vlm_attributes["garment_class"]["evidence"])

    return GarmentAttributes(
        fixture=fixture_id,
        role=role,
        garment_class=garment_class,
        sleeve_length=sleeve_length,
        skirt_style=skirt_style,
        source_evidence=" | ".join(part for part in evidence_parts if part) or "pipeline",
    )


def _lookup_manifest_template_override(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
) -> str | None:
    manifest = load_manifest(repo_root / DEFAULT_CATALOG_MANIFEST)
    for case in manifest.get("cases", []):
        if not isinstance(case, dict):
            continue
        if case.get("fixture") != fixture_id or case.get("role") != role:
            continue
        explicit = case.get("template_override")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        if case.get("confidence") == "high" and isinstance(case.get("template_id"), str):
            return str(case["template_id"])
    return None


def select_template_for_pipeline(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    vlm_attributes: dict[str, dict[str, str]] | None,
    user_override: UserOverrideConfig | None,
    attributes_path: Path = DEFAULT_GARMENT_ATTRIBUTES,
) -> TemplateSelection:
    reviewed = load_garment_attributes(attributes_path)
    reviewed_record = garment_attributes_for_case(reviewed, fixture=fixture_id, role=role)
    selector_input = garment_attributes_from_vlm(
        fixture_id=fixture_id,
        role=role,
        vlm_attributes=vlm_attributes,
        user_override=user_override,
        reviewed_record=reviewed_record,
    )
    user_template_override = user_override.template_override if user_override else None
    preliminary = select_template_from_attributes(
        selector_input,
        template_override=user_template_override,
    )
    template_override = user_template_override
    if template_override is None and preliminary.confidence == "low":
        template_override = _lookup_manifest_template_override(
            repo_root=repo_root,
            fixture_id=fixture_id,
            role=role,
        )
    if template_override == preliminary.template_id and preliminary.override_applied:
        return preliminary
    return select_template_from_attributes(selector_input, template_override=template_override)


def validate_cutout_provenance(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    cutout_root: Path = DEFAULT_CUTOUT_ROOT,
) -> str:
    cutout = repo_root / catalog_cutout_path(
        cutout_root=cutout_root,
        fixture_id=fixture_id,
        role=role,
    )
    if not cutout.is_file():
        raise CatalogPipelineError(f"segmented cutout missing: {cutout}")
    digest = sha256_file(cutout)
    return digest


def validate_detail_crop_for_pipeline(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    cutout_path: Path,
    detail_root: Path = DEFAULT_DETAIL_CROP_ROOT,
) -> dict[str, Any]:
    if role not in {"top", "dress"}:
        return {"included": False, "reason": "not_applicable_for_role"}
    detail_abs = repo_root / detail_crop_output_path(
        detail_root=detail_root,
        fixture_id=fixture_id,
        role=role,
    )
    result = extract_detail_crop(cutout_path, output_path=detail_abs)
    provenance = {
        "included": result.included,
        "reason": result.reason,
        "source_bbox": result.source_bbox,
        "crop_bbox": result.crop_bbox,
    }
    if result.reason in _CONTAMINATED_DETAIL_REASONS:
        raise CatalogPipelineError(
            f"detail crop rejected as contaminated: {result.reason} for {fixture_id}/{role}"
        )
    return provenance


def pipeline_artifact_output_path(
    *,
    artifact_root: Path,
    fixture_id: str,
    role: str,
    template_id: str,
    user_override: UserOverrideConfig | None,
) -> Path:
    if user_override is not None and user_override.geometry_reference_override is not None:
        return artifact_root / f"{fixture_id}_{role}_{template_id}.geometry_reference.request.json"
    if user_override is not None:
        return artifact_root / f"{fixture_id}_{role}_{template_id}.user_corrected.request.json"
    return artifact_root / f"{fixture_id}_{role}_{template_id}.pipeline.request.json"


def build_pipeline_request_artifact(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    template_id: str,
    template_selection: TemplateSelection,
    extraction_record: dict[str, Any] | None,
    user_override: UserOverrideConfig | None,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
) -> tuple[dict[str, Any], Path]:
    if user_override is not None and user_override.geometry_reference_override is not None:
        if extraction_record is None:
            raise CatalogPipelineError(
                f"geometry reference override for {fixture_id}/{role} requires VLM attributes"
            )
        artifact = build_geometry_reference_request_artifact(
            repo_root=repo_root,
            fixture_id=fixture_id,
            role=role,
            template_id=template_id,
            extraction_record=extraction_record,
            user_override=user_override,
            template_selection=template_selection.to_metadata(),
        )
        artifact_path = repo_root / pipeline_artifact_output_path(
            artifact_root=artifact_root,
            fixture_id=fixture_id,
            role=role,
            template_id=template_id,
            user_override=user_override,
        )
        write_request_artifact(artifact, output_path=artifact_path)
        validate_geometry_reference_request_artifact(artifact, repo_root=repo_root)
        return artifact, artifact_path
    if user_override is not None:
        if extraction_record is None:
            raise CatalogPipelineError(
                f"user override for {fixture_id}/{role} requires VLM attribute extraction"
            )
        artifact = build_user_corrected_request_artifact(
            repo_root=repo_root,
            fixture_id=fixture_id,
            role=role,
            template_id=template_id,
            extraction_record=extraction_record,
            user_override=user_override,
        )
    else:
        artifact = build_request_artifact(
            repo_root=repo_root,
            fixture_id=fixture_id,
            role=role,
            template_id=template_id,
            template_selection=template_selection.to_metadata(),
        )
    artifact["template_selection"] = template_selection.to_metadata()
    artifact_path = repo_root / pipeline_artifact_output_path(
        artifact_root=artifact_root,
        fixture_id=fixture_id,
        role=role,
        template_id=template_id,
        user_override=user_override,
    )
    write_request_artifact(artifact, output_path=artifact_path)
    validate_request_artifact(artifact, repo_root=repo_root)
    return artifact, artifact_path


def sanitize_pipeline_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(metadata)
    sanitized.pop("prompt_text", None)
    return sanitized


def resolve_user_override_for_case(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    override_path: Path | None,
) -> tuple[UserOverrideConfig | None, Path | None]:
    """Load an explicit or default user override when present."""
    if override_path is not None and override_path.is_file():
        user_override = load_user_override(override_path)
        if user_override.fixture != fixture_id or user_override.role != role:
            raise CatalogPipelineError(
                f"override fixture/role mismatch: expected {fixture_id}/{role}, "
                f"got {user_override.fixture}/{user_override.role}"
            )
        return user_override, override_path

    default_path = repo_root / default_override_path(fixture_id=fixture_id, role=role)
    if default_path.is_file():
        return load_user_override(default_path), default_path
    return None, None


def _sync_metadata_output_paths(
    metadata: dict[str, Any],
    *,
    target_paths: PipelineOutputPaths,
    repo_root: Path,
) -> None:
    outputs = metadata.get("outputs")
    if not isinstance(outputs, dict):
        return
    raw_rel = repo_relative_path(target_paths.raw_1k_path, repo_root=repo_root)
    catalog_rel = repo_relative_path(target_paths.catalog_512_path, repo_root=repo_root)
    if "raw" in outputs and isinstance(outputs["raw"], dict):
        outputs["raw"]["path"] = raw_rel
    if "catalog" in outputs and isinstance(outputs["catalog"], dict):
        outputs["catalog"]["path"] = catalog_rel
    if "comparison_512" in outputs and isinstance(outputs["comparison_512"], dict):
        outputs["comparison_512"]["path"] = catalog_rel


def _apply_artifact_fields_to_promoted_metadata(
    promoted: dict[str, Any],
    *,
    artifact: dict[str, Any],
    artifact_path: Path,
    repo_root: Path,
    template_selection: TemplateSelection | None = None,
) -> None:
    promoted["namespace"] = PRODUCTION_NAMESPACE
    promoted["generation_mode"] = PIPELINE_GENERATION_MODE
    promoted["metadata_schema_version"] = PIPELINE_METADATA_SCHEMA_VERSION
    promoted["prompt_policy_version"] = artifact.get("prompt_policy_version")
    promoted["reused"] = True
    promoted["generation_calls"] = 0
    promoted["estimated_cost_usd"] = 0.0
    promoted["artifact_path"] = repo_relative_path(artifact_path, repo_root=repo_root)
    if template_selection is not None:
        promoted["template_selection"] = template_selection.to_metadata()
    elif artifact.get("template_selection") is not None:
        promoted["template_selection"] = artifact["template_selection"]
    if artifact.get("user_override") is not None:
        promoted["user_override"] = artifact["user_override"]
    if artifact.get("geometry_reference_override") is not None:
        promoted["geometry_reference_override"] = artifact["geometry_reference_override"]
    if artifact.get("detail_reference_provenance") is not None:
        promoted["detail_reference_provenance"] = artifact["detail_reference_provenance"]
    if artifact.get("vlm_attribute_json_sha256") is not None:
        promoted["vlm_attribute_json_sha256"] = artifact["vlm_attribute_json_sha256"]
    promoted.pop("prompt_text", None)


def pipeline_metadata_matches_artifact(metadata: dict[str, Any], artifact: dict[str, Any]) -> bool:
    if metadata.get("generation_mode") != PIPELINE_GENERATION_MODE:
        return False
    if metadata.get("namespace") != PRODUCTION_NAMESPACE:
        return False
    if metadata.get("prompt_policy_version") != artifact.get("prompt_policy_version"):
        return False
    return metadata_matches_artifact(metadata, artifact)


def load_reusable_pipeline_result(
    *,
    repo_root: Path,
    artifact: dict[str, Any],
    output_paths: PipelineOutputPaths,
) -> dict[str, Any] | None:
    metadata = load_existing_result_metadata(output_paths.metadata_path)
    if metadata is None:
        return None
    if not pipeline_metadata_matches_artifact(metadata, artifact):
        return None
    try:
        validate_canonical_outputs(output_paths.canonical_paths())
    except CatalogGenerationError:
        return None
    return metadata


def reference_output_paths(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    namespace: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> PipelineOutputPaths:
    case_dir = production_case_dir(
        output_root=repo_root / output_root,
        fixture_id=fixture_id,
        namespace=namespace,
    )
    return PipelineOutputPaths(
        raw_1k_path=case_dir / f"{role}_1k_raw.png",
        catalog_512_path=case_dir / f"{role}.png",
        metadata_path=case_dir / f"{role}.run.json",
        artifact_path=case_dir / f"{role}.artifact.json",
    )


def check_reference_promotion_eligible(
    *,
    repo_root: Path,
    artifact: dict[str, Any],
    reference_namespace: str = REFERENCE_NAMESPACE,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> str | None:
    """Return reference namespace when promotion is hash-safe; no file writes."""
    case = artifact["case"]
    reference = reference_output_paths(
        repo_root=repo_root,
        fixture_id=case["fixture"],
        role=case["role"],
        namespace=reference_namespace,
        output_root=output_root,
    )
    reference_metadata = load_existing_result_metadata(reference.metadata_path)
    if reference_metadata is None:
        return None
    if reference_metadata.get("prompt_sha256") != sha256_text(artifact["prompt"]):
        return None
    recorded_inputs = {
        (item["order"], item["role"], item["path"], item["sha256"])
        for item in reference_metadata.get("input_images", [])
    }
    expected_inputs = {
        (item["order"], item["role"], item["path"], item["sha256"])
        for item in artifact.get("images", [])
    }
    if recorded_inputs != expected_inputs:
        return None
    if not reference.raw_1k_path.is_file() or not reference.catalog_512_path.is_file():
        return None
    return reference_namespace


def try_promote_reference_output(
    *,
    repo_root: Path,
    artifact: dict[str, Any],
    target_paths: PipelineOutputPaths,
    reference_namespace: str = REFERENCE_NAMESPACE,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> str | None:
    case = artifact["case"]
    eligible = check_reference_promotion_eligible(
        repo_root=repo_root,
        artifact=artifact,
        reference_namespace=reference_namespace,
        output_root=output_root,
    )
    if eligible is None:
        return None

    reference = reference_output_paths(
        repo_root=repo_root,
        fixture_id=case["fixture"],
        role=case["role"],
        namespace=reference_namespace,
        output_root=output_root,
    )
    reference_metadata = load_existing_result_metadata(reference.metadata_path)
    if reference_metadata is None:
        return None

    for src, dst in (
        (reference.raw_1k_path, target_paths.raw_1k_path),
        (reference.catalog_512_path, target_paths.catalog_512_path),
    ):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    promoted = dict(reference_metadata)
    promoted["reuse_source"] = reference_namespace
    _apply_artifact_fields_to_promoted_metadata(
        promoted,
        artifact=artifact,
        artifact_path=target_paths.artifact_path,
        repo_root=repo_root,
    )
    promoted["production_policy"] = production_policy(
        promoted_from_reference=reference_namespace,
    )
    _sync_metadata_output_paths(
        promoted,
        target_paths=target_paths,
        repo_root=repo_root,
    )
    target_paths.metadata_path.write_text(serialize_run_metadata(promoted), encoding="utf-8")
    return reference_namespace


def _parse_observation_fixture_role(observation_id: str) -> tuple[str, str]:
    fixture, role = observation_id.rsplit("_", 1)
    return fixture, role


def check_identity_alias_reuse_eligible(
    *,
    repo_root: Path,
    observation_id: str,
    registry_path: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> IdentityAliasTarget | None:
    """Return alias target when canonical production outputs exist; no file writes."""
    resolved_registry = registry_path or default_registry_path(repo_root)
    alias_target = lookup_identity_alias(observation_id, registry_path=resolved_registry)
    if alias_target is None:
        return None

    canonical_fixture, canonical_role = _parse_observation_fixture_role(
        alias_target.canonical_observation_id
    )
    canonical_paths = reference_output_paths(
        repo_root=repo_root,
        fixture_id=canonical_fixture,
        role=canonical_role,
        namespace=PRODUCTION_NAMESPACE,
        output_root=output_root,
    )
    if not canonical_paths.raw_1k_path.is_file() or not canonical_paths.catalog_512_path.is_file():
        return None
    canonical_metadata = load_existing_result_metadata(canonical_paths.metadata_path)
    if canonical_metadata is None:
        return None
    return alias_target


def try_reuse_identity_canonical_output(
    *,
    repo_root: Path,
    observation_id: str,
    artifact: dict[str, Any],
    artifact_path: Path,
    target_paths: PipelineOutputPaths,
    template_selection: TemplateSelection,
    vlm_record_sha256: str | None,
    registry_path: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> IdentityAliasTarget | None:
    """Copy canonical identity-group output bytes to an alias observation without billing."""
    alias_target = check_identity_alias_reuse_eligible(
        repo_root=repo_root,
        observation_id=observation_id,
        registry_path=registry_path,
        output_root=output_root,
    )
    if alias_target is None:
        return None

    canonical_fixture, canonical_role = _parse_observation_fixture_role(
        alias_target.canonical_observation_id
    )
    canonical_paths = reference_output_paths(
        repo_root=repo_root,
        fixture_id=canonical_fixture,
        role=canonical_role,
        namespace=PRODUCTION_NAMESPACE,
        output_root=output_root,
    )
    canonical_metadata = load_existing_result_metadata(canonical_paths.metadata_path)
    if canonical_metadata is None:
        return None

    for src, dst in (
        (canonical_paths.raw_1k_path, target_paths.raw_1k_path),
        (canonical_paths.catalog_512_path, target_paths.catalog_512_path),
    ):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    alias_metadata = dict(canonical_metadata)
    alias_metadata["identity_reuse"] = {
        "garment_id": alias_target.garment_id,
        "canonical_observation_id": alias_target.canonical_observation_id,
        "reason": "user_confirmed",
        "generation_calls": 0,
    }
    alias_metadata["reuse_source"] = f"identity:{alias_target.canonical_observation_id}"
    _apply_artifact_fields_to_promoted_metadata(
        alias_metadata,
        artifact=artifact,
        artifact_path=artifact_path,
        repo_root=repo_root,
        template_selection=template_selection,
    )
    alias_metadata["production_policy"] = production_policy(
        identity_reuse=alias_target.canonical_observation_id,
    )
    if vlm_record_sha256 is not None:
        alias_metadata["vlm_attribute_json_sha256"] = vlm_record_sha256
    _sync_metadata_output_paths(
        alias_metadata,
        target_paths=target_paths,
        repo_root=repo_root,
    )
    target_paths.metadata_path.write_text(serialize_run_metadata(alias_metadata), encoding="utf-8")
    return alias_target


def save_pipeline_outputs(
    *,
    repo_root: Path,
    artifact: dict[str, Any],
    artifact_path: Path,
    raw_image: Image.Image,
    raw_mime_type: str | None,
    catalog_image: Image.Image,
    normalization: dict[str, Any],
    request_settings: dict[str, Any],
    request_utc: str,
    elapsed_seconds: float,
    generation_calls: int,
    output_paths: PipelineOutputPaths,
    template_selection: TemplateSelection,
    vlm_record_sha256: str | None,
    user_override: UserOverrideConfig | None,
    texture_qc: dict[str, Any],
    reused: bool = False,
    reuse_source: str | None = None,
) -> dict[str, Any]:
    output_paths.raw_1k_path.parent.mkdir(parents=True, exist_ok=True)
    raw_image.save(output_paths.raw_1k_path, format="PNG")
    catalog_image.save(output_paths.catalog_512_path, format="PNG")

    metadata = build_run_metadata(
        artifact_path=repo_relative_path(artifact_path, repo_root=repo_root),
        artifact=artifact,
        request_settings=request_settings,
        request_utc=request_utc,
        elapsed_seconds=elapsed_seconds,
        raw_path=repo_relative_path(output_paths.raw_1k_path, repo_root=repo_root),
        raw_width=raw_image.width,
        raw_height=raw_image.height,
        raw_sha256=sha256_file(output_paths.raw_1k_path),
        raw_mime_type=raw_mime_type,
        catalog_path=repo_relative_path(output_paths.catalog_512_path, repo_root=repo_root),
        catalog_sha256=sha256_file(output_paths.catalog_512_path),
        normalization=normalization,
        generation_calls=generation_calls,
        image_size=CANONICAL_IMAGE_SIZE,
        reused=reused,
        reuse_source=reuse_source,
    )
    metadata["generation_mode"] = PIPELINE_GENERATION_MODE
    metadata["namespace"] = PRODUCTION_NAMESPACE
    metadata["metadata_schema_version"] = PIPELINE_METADATA_SCHEMA_VERSION
    metadata["prompt_policy_version"] = artifact.get("prompt_policy_version")
    metadata["template_selection"] = template_selection.to_metadata()
    metadata["estimated_cost_usd"] = CANONICAL_COST_1K_USD if generation_calls else 0.0
    metadata["production_policy"] = production_policy()
    if vlm_record_sha256 is not None:
        metadata["vlm_attribute_json_sha256"] = vlm_record_sha256
    if user_override is not None:
        metadata["user_override"] = artifact.get("user_override")
    if artifact.get("geometry_reference_override") is not None:
        metadata["geometry_reference_override"] = artifact["geometry_reference_override"]
    if artifact.get("detail_reference_provenance") is not None:
        metadata["detail_reference_provenance"] = artifact["detail_reference_provenance"]
    metadata["texture_qc"] = texture_qc
    metadata.pop("prompt_text", None)
    output_paths.metadata_path.write_text(serialize_run_metadata(metadata), encoding="utf-8")
    return metadata


def build_pipeline_plan(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    vlm_path: Path | None = None,
    override_path: Path | None = None,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    attributes_path: Path = DEFAULT_GARMENT_ATTRIBUTES,
) -> PipelinePlan:
    manifest = load_manifest(repo_root / DEFAULT_CATALOG_MANIFEST)
    if manifest_case_for(manifest, fixture=fixture_id, role=role) is None:
        raise CatalogPipelineError(manifest_role_hint(manifest, fixture=fixture_id, role=role))

    validate_cutout_provenance(repo_root=repo_root, fixture_id=fixture_id, role=role)

    user_override, override_path = resolve_user_override_for_case(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        override_path=override_path,
    )

    extraction_record: dict[str, Any] | None = None
    vlm_record_sha256: str | None = None
    vlm_attributes: dict[str, dict[str, str]] | None = None

    resolved_vlm = vlm_path
    if resolved_vlm is None:
        candidate = repo_root / default_vlm_attributes_path(fixture_id=fixture_id, role=role)
        if candidate.is_file():
            resolved_vlm = candidate
    if resolved_vlm is not None and resolved_vlm.is_file():
        extraction_record = load_extraction_record(resolved_vlm)
        vlm_record_sha256 = extraction_record_sha256(extraction_record)
        vlm_attributes = extraction_record["attributes"]

    template_selection = select_template_for_pipeline(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        vlm_attributes=vlm_attributes,
        user_override=user_override,
        attributes_path=repo_root / attributes_path,
    )
    review_required = (
        template_selection.confidence == "low" and not template_selection.override_applied
    )

    cutout = repo_root / catalog_cutout_path(
        cutout_root=DEFAULT_CUTOUT_ROOT,
        fixture_id=fixture_id,
        role=role,
    )
    validate_detail_crop_for_pipeline(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        cutout_path=cutout,
    )

    artifact, artifact_path = build_pipeline_request_artifact(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        template_id=template_selection.template_id,
        template_selection=template_selection,
        extraction_record=extraction_record,
        user_override=user_override,
        artifact_root=artifact_root,
    )

    case_dir = production_case_dir(
        output_root=repo_root / output_root,
        fixture_id=fixture_id,
    )
    output_paths = production_output_paths(
        case_dir=case_dir,
        role=role,
        artifact_path=artifact_path,
    )

    reusable = load_reusable_pipeline_result(
        repo_root=repo_root,
        artifact=artifact,
        output_paths=output_paths,
    )
    observation_id = catalog_id(fixture_id, role)
    identity_alias = check_identity_alias_reuse_eligible(
        repo_root=repo_root,
        observation_id=observation_id,
    )
    if reusable is not None:
        reuse_status = "reuse_production"
        billable = False
    elif identity_alias is not None:
        reuse_status = "reuse_identity_alias"
        billable = False
    else:
        reuse_status = "pending"
        billable = True

    return PipelinePlan(
        fixture_id=fixture_id,
        role=role,
        template_id=template_selection.template_id,
        template_selection=template_selection,
        artifact=artifact,
        artifact_rel=repo_relative_path(artifact_path, repo_root=repo_root),
        output_paths=output_paths,
        vlm_record_sha256=vlm_record_sha256,
        override_applied=user_override is not None,
        review_required=review_required,
        reuse_status=reuse_status,
        billable=billable,
        estimated_cost_usd=CANONICAL_COST_1K_USD if billable else 0.0,
        reference_promotion=None,
    )


def run_pipeline_case(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    dry_run: bool = False,
    regenerate: bool = False,
    vlm_path: Path | None = None,
    override_path: Path | None = None,
    config: GeminiCatalogConfig | None = None,
    client: Any | None = None,
    now: datetime | None = None,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> PipelineResult:
    plan = build_pipeline_plan(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        vlm_path=vlm_path,
        override_path=override_path,
        artifact_root=artifact_root,
        output_root=output_root,
    )

    if plan.review_required:
        raise CatalogPipelineError(
            f"template selection for {fixture_id}/{role} requires review: "
            f"{plan.template_selection.reason}"
        )

    if dry_run:
        reusable = load_reusable_pipeline_result(
            repo_root=repo_root,
            artifact=plan.artifact,
            output_paths=plan.output_paths,
        )
        if reusable is not None:
            promotion = None
            reuse_status = "reuse_production"
        else:
            identity_alias = check_identity_alias_reuse_eligible(
                repo_root=repo_root,
                observation_id=catalog_id(fixture_id, role),
            )
            if identity_alias is not None:
                promotion = None
                reuse_status = "reuse_identity_alias"
            else:
                promotion = check_reference_promotion_eligible(
                    repo_root=repo_root,
                    artifact=plan.artifact,
                )
                reuse_status = plan.reuse_status
                if promotion is not None:
                    reuse_status = f"promote_{promotion}"
        return PipelineResult(
            plan=replace(
                plan,
                reuse_status=reuse_status,
                billable=False,
                estimated_cost_usd=0.0,
                reference_promotion=promotion,
            ),
            metadata=None,
            status="dry_run",
            generation_calls=0,
        )

    reusable = load_reusable_pipeline_result(
        repo_root=repo_root,
        artifact=plan.artifact,
        output_paths=plan.output_paths,
    )
    if reusable is not None and not regenerate:
        return PipelineResult(
            plan=replace(plan, reuse_status="reuse_production", billable=False),
            metadata=reusable,
            status="reused",
            generation_calls=0,
        )

    if not regenerate:
        identity_reused = try_reuse_identity_canonical_output(
            repo_root=repo_root,
            observation_id=catalog_id(fixture_id, role),
            artifact=plan.artifact,
            artifact_path=plan.output_paths.artifact_path,
            target_paths=plan.output_paths,
            template_selection=plan.template_selection,
            vlm_record_sha256=plan.vlm_record_sha256,
        )
        if identity_reused is not None:
            alias_metadata = load_existing_result_metadata(plan.output_paths.metadata_path)
            return PipelineResult(
                plan=replace(
                    plan,
                    reuse_status="reuse_identity_alias",
                    billable=False,
                    estimated_cost_usd=0.0,
                ),
                metadata=alias_metadata,
                status="identity_reused",
                generation_calls=0,
            )

    if not regenerate:
        promotion = try_promote_reference_output(
            repo_root=repo_root,
            artifact=plan.artifact,
            target_paths=plan.output_paths,
        )
        if promotion is not None:
            promoted_metadata = load_existing_result_metadata(plan.output_paths.metadata_path)
            return PipelineResult(
                plan=replace(
                    plan,
                    reuse_status=f"promote_{promotion}",
                    billable=False,
                    estimated_cost_usd=0.0,
                    reference_promotion=promotion,
                ),
                metadata=promoted_metadata,
                status="promoted",
                generation_calls=0,
            )

    if not regenerate and plan.billable:
        raise CatalogPipelineError(
            "generation would incur a billable API call; pass --regenerate to opt in explicitly"
        )

    from google.genai import types

    artifact_path = plan.output_paths.artifact_path
    artifact = plan.artifact
    model_id = artifact.get("gemini_model_id", NANO_BANANA_2_MODEL_ID)
    resolved_config = config or GeminiCatalogConfig(model_id=model_id)
    gemini_client = client or build_gemini_client(config=resolved_config)
    contents = build_generation_contents(artifact=artifact, repo_root=repo_root)
    request_settings = generation_request_settings(
        model_id=model_id, image_size=CANONICAL_IMAGE_SIZE
    )
    request_utc = (now or datetime.now(tz=UTC)).isoformat()

    started = time.perf_counter()
    try:
        response = gemini_client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="1:1", image_size=CANONICAL_IMAGE_SIZE),
            ),
        )
    except Exception as exc:
        raise CatalogGenerationError(sanitize_api_error(str(exc))) from exc
    elapsed = time.perf_counter() - started

    images = extract_response_images(response)
    if not images:
        raise CatalogGenerationError("API response contained no image parts")

    raw = images[0]
    catalog_image, normalization = normalize_catalog_output(raw.image)
    cutout = repo_root / artifact["images"][0]["path"]
    texture_qc = compare_texture_heuristic(
        source_image=Image.open(cutout).convert("RGB"),
        output_image=catalog_image,
        role=role,
    )

    user_override, _ = resolve_user_override_for_case(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        override_path=override_path,
    )

    metadata = save_pipeline_outputs(
        repo_root=repo_root,
        artifact=artifact,
        artifact_path=artifact_path,
        raw_image=raw.image.convert("RGB"),
        raw_mime_type=raw.mime_type,
        catalog_image=catalog_image,
        normalization=normalization,
        request_settings=request_settings,
        request_utc=request_utc,
        elapsed_seconds=elapsed,
        generation_calls=1,
        output_paths=plan.output_paths,
        template_selection=plan.template_selection,
        vlm_record_sha256=plan.vlm_record_sha256,
        user_override=user_override,
        texture_qc=texture_qc.to_metadata(),
    )
    validate_canonical_outputs(plan.output_paths.canonical_paths())
    return PipelineResult(
        plan=replace(plan, reuse_status="generated", billable=True),
        metadata=metadata,
        status="generated",
        generation_calls=1,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Production catalog pipeline: segmented cutout → VLM attributes → "
            "template selection → one 1K Gemini call → local 512 derivative."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--fixture")
    parser.add_argument("--role", choices=["top", "bottom", "dress"])
    parser.add_argument("--from-fixture", type=int, help="Inclusive batch range start.")
    parser.add_argument("--to-fixture", type=int, help="Inclusive batch range end.")
    parser.add_argument("--vlm-attributes", type=Path, help="VLM extraction JSON path.")
    parser.add_argument("--override", type=Path, help="User override JSON path.")
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs, build artifacts, and report cost/reuse plan without API calls.",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Opt in to a billable API call when outputs are missing or stale.",
    )
    parser.add_argument("--credentials-file", type=Path)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    vlm_path = args.vlm_attributes
    if vlm_path is not None and not vlm_path.is_absolute():
        vlm_path = repo_root / vlm_path
    override_path = args.override
    if override_path is not None and not override_path.is_absolute():
        override_path = repo_root / override_path

    config = GeminiCatalogConfig(credentials_file=args.credentials_file)

    batch_cases: list[tuple[str, str]] = []
    if args.from_fixture is not None or args.to_fixture is not None:
        if args.from_fixture is None or args.to_fixture is None:
            print(
                "error: batch mode requires both --from-fixture and --to-fixture", file=sys.stderr
            )
            raise SystemExit(1)
        if args.fixture or args.role:
            print("error: --fixture/--role cannot be combined with batch range", file=sys.stderr)
            raise SystemExit(1)
        fixture_ids = resolve_plan1_fixtures(
            from_fixture=args.from_fixture,
            to_fixture=args.to_fixture,
        )
        manifest = load_manifest(repo_root / DEFAULT_CATALOG_MANIFEST)
        for case in iter_cases(manifest, fixture_ids=fixture_ids):
            batch_cases.append((case["fixture"], case["role"]))
    elif args.fixture and args.role:
        batch_cases.append((args.fixture, args.role))
    else:
        print(
            "error: specify --fixture and --role, or --from-fixture and --to-fixture",
            file=sys.stderr,
        )
        raise SystemExit(1)

    total_calls = 0
    total_cost = 0.0
    failures = 0
    for fixture_id, role in batch_cases:
        try:
            result = run_pipeline_case(
                repo_root=repo_root,
                fixture_id=fixture_id,
                role=role,
                dry_run=args.dry_run,
                regenerate=args.regenerate,
                vlm_path=vlm_path,
                override_path=override_path,
                config=config,
                artifact_root=args.artifact_root,
                output_root=args.output_root,
            )
        except (
            CatalogPipelineError,
            CatalogGenerationError,
            CatalogRequestArtifactError,
            UserOverrideError,
        ) as exc:
            failures += 1
            print(f"error: {fixture_id}/{role}: {exc}", file=sys.stderr)
            continue

        plan = result.plan
        print(f"ok: pipeline {result.status} for {plan.fixture_id}/{plan.role}")
        print(f"  template: {plan.template_id} ({plan.template_selection.confidence})")
        print(f"  artifact: {plan.artifact_rel}")
        print(f"  reuse: {plan.reuse_status}")
        print(f"  override: {plan.override_applied}")
        print(f"  review_required: {plan.review_required}")
        print(f"  generation_calls: {result.generation_calls}")
        print(f"  estimated_cost_usd: {plan.estimated_cost_usd:.4f}")
        if plan.reference_promotion:
            print(f"  reference_promotion: {plan.reference_promotion}")
        if result.metadata is not None:
            catalog = result.metadata.get("outputs", {}).get("catalog", {})
            if catalog.get("path"):
                print(f"  output: {catalog['path']}")
        total_calls += result.generation_calls
        total_cost += plan.estimated_cost_usd

    if len(batch_cases) > 1:
        print(
            f"batch summary: cases={len(batch_cases)} failures={failures} "
            f"generation_calls={total_calls} estimated_cost_usd={total_cost:.4f}"
        )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
