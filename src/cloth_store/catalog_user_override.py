"""Versioned user override schema for catalog generation pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OVERRIDE_SCHEMA_VERSION = 1
DEFAULT_OVERRIDE_ROOT = Path("bench/catalog_generation/overrides")
DEFAULT_PRECEDENCE = "user_override > high_confidence_source_vlm > template_geometry_only"

_REQUIRED_FIELDS = frozenset({"schema_version", "fixture", "role", "garment_class", "reason"})
_OPTIONAL_LIST_FIELDS = frozenset(
    {"overridden_vlm_fields", "prohibited_conversions", "presentation_requirements", "prompt_lines"}
)
_GEOMETRY_OVERRIDE_REQUIRED = frozenset(
    {
        "derived_geometry_path",
        "geometry_source_fixture",
        "geometry_source_path",
    }
)


class UserOverrideError(ValueError):
    """Raised when a user override JSON record is invalid."""


@dataclass(frozen=True)
class GeometryReferenceOverride:
    derived_geometry_path: str
    geometry_source_fixture: str
    geometry_source_path: str
    derived_geometry_sha256: str | None = None
    geometry_source_sha256: str | None = None
    prompt_policy_version: int = 1

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> GeometryReferenceOverride:
        missing = sorted(_GEOMETRY_OVERRIDE_REQUIRED - set(record))
        if missing:
            raise UserOverrideError(
                f"geometry_reference_override missing required fields: {', '.join(missing)}"
            )
        for field in _GEOMETRY_OVERRIDE_REQUIRED:
            value = record[field]
            if not isinstance(value, str) or not value.strip():
                raise UserOverrideError(
                    f"geometry_reference_override.{field} must be a non-empty string"
                )
        derived_sha = record.get("derived_geometry_sha256")
        source_sha = record.get("geometry_source_sha256")
        if derived_sha is not None and not isinstance(derived_sha, str):
            raise UserOverrideError("derived_geometry_sha256 must be a string when present")
        if source_sha is not None and not isinstance(source_sha, str):
            raise UserOverrideError("geometry_source_sha256 must be a string when present")
        policy_version = record.get("prompt_policy_version", 1)
        if not isinstance(policy_version, int):
            raise UserOverrideError("prompt_policy_version must be an integer")
        return cls(
            derived_geometry_path=str(record["derived_geometry_path"]),
            geometry_source_fixture=str(record["geometry_source_fixture"]),
            geometry_source_path=str(record["geometry_source_path"]),
            derived_geometry_sha256=derived_sha,
            geometry_source_sha256=source_sha,
            prompt_policy_version=policy_version,
        )

    def to_artifact_block(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "derived_geometry_path": self.derived_geometry_path,
            "geometry_source_fixture": self.geometry_source_fixture,
            "geometry_source_path": self.geometry_source_path,
            "prompt_policy_version": self.prompt_policy_version,
        }
        if self.derived_geometry_sha256 is not None:
            block["derived_geometry_sha256"] = self.derived_geometry_sha256
        if self.geometry_source_sha256 is not None:
            block["geometry_source_sha256"] = self.geometry_source_sha256
        return block


@dataclass(frozen=True)
class InputRolePolicy:
    include_detail_reference: bool | None = None

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> InputRolePolicy:
        include_detail = record.get("include_detail_reference")
        if include_detail is not None and not isinstance(include_detail, bool):
            raise UserOverrideError("include_detail_reference must be a boolean when present")
        return cls(include_detail_reference=include_detail)

    def to_artifact_block(self) -> dict[str, Any]:
        block: dict[str, Any] = {}
        if self.include_detail_reference is not None:
            block["include_detail_reference"] = self.include_detail_reference
        return block


@dataclass(frozen=True)
class UserOverrideConfig:
    schema_version: int
    fixture: str
    role: str
    garment_class: str
    reason: str
    overridden_vlm_fields: frozenset[str]
    prohibited_conversions: tuple[str, ...]
    presentation_requirements: tuple[str, ...]
    prompt_lines: tuple[str, ...]
    presentation_mode: str
    precedence: str
    namespace: str | None
    template_override: str | None
    sheen_constraint: str | None
    geometry_reference_override: GeometryReferenceOverride | None
    input_role_policy: InputRolePolicy | None

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> UserOverrideConfig:
        validated = validate_user_override(record)
        geo_record = validated.get("geometry_reference_override")
        geo_override = (
            GeometryReferenceOverride.from_record(geo_record)
            if isinstance(geo_record, dict)
            else None
        )
        role_policy_record = validated.get("input_role_policy")
        input_role_policy = (
            InputRolePolicy.from_record(role_policy_record)
            if isinstance(role_policy_record, dict)
            else None
        )
        return cls(
            schema_version=int(validated["schema_version"]),
            fixture=str(validated["fixture"]),
            role=str(validated["role"]),
            garment_class=str(validated["garment_class"]).strip().lower(),
            reason=str(validated["reason"]).strip(),
            overridden_vlm_fields=frozenset(validated.get("overridden_vlm_fields", [])),
            prohibited_conversions=tuple(validated.get("prohibited_conversions", [])),
            presentation_requirements=tuple(validated.get("presentation_requirements", [])),
            prompt_lines=tuple(validated.get("prompt_lines", [])),
            presentation_mode=str(validated.get("presentation_mode", "text_only")),
            precedence=str(validated.get("precedence", DEFAULT_PRECEDENCE)),
            namespace=validated.get("namespace"),
            template_override=validated.get("template_override"),
            sheen_constraint=validated.get("sheen_constraint"),
            geometry_reference_override=geo_override,
            input_role_policy=input_role_policy,
        )

    def to_artifact_block(
        self,
        *,
        injected_high_confidence_fields: list[str],
        vlm_attribute_json_sha256: str,
        sheen_constraint: str,
    ) -> dict[str, Any]:
        block: dict[str, Any] = {
            "garment_class": self.garment_class,
            "reason": self.reason,
            "overridden_vlm_fields": sorted(self.overridden_vlm_fields),
            "prohibited_conversions": list(self.prohibited_conversions),
            "presentation_mode": self.presentation_mode,
            "precedence": self.precedence,
            "vlm_attribute_json_sha256": vlm_attribute_json_sha256,
            "injected_high_confidence_fields": injected_high_confidence_fields,
            "sheen_constraint": sheen_constraint,
        }
        if self.namespace is not None:
            block["namespace"] = self.namespace
        if self.prompt_lines:
            block["prompt_lines"] = list(self.prompt_lines)
        return block


def validate_user_override(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise UserOverrideError("override must be a JSON object")

    missing = sorted(_REQUIRED_FIELDS - set(record))
    if missing:
        raise UserOverrideError(f"override missing required fields: {', '.join(missing)}")

    version = record["schema_version"]
    if version != OVERRIDE_SCHEMA_VERSION:
        raise UserOverrideError(
            f"unsupported override schema_version {version!r}, expected {OVERRIDE_SCHEMA_VERSION}"
        )

    for field in _OPTIONAL_LIST_FIELDS:
        value = record.get(field)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise UserOverrideError(f"{field} must be a list of strings")

    prompt_lines = record.get("prompt_lines", [])
    if prompt_lines and any(not line.strip() for line in prompt_lines):
        raise UserOverrideError("prompt_lines entries must be non-empty strings")

    fixture = record["fixture"]
    role = record["role"]
    if not isinstance(fixture, str) or not fixture.strip():
        raise UserOverrideError("fixture must be a non-empty string")
    if role not in {"top", "bottom", "dress"}:
        raise UserOverrideError(f"unsupported role {role!r}")

    garment_class = record["garment_class"]
    if not isinstance(garment_class, str) or not garment_class.strip():
        raise UserOverrideError("garment_class must be a non-empty string")

    reason = record["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise UserOverrideError("reason must be a non-empty string")

    template_override = record.get("template_override")
    if template_override is not None and not isinstance(template_override, str):
        raise UserOverrideError("template_override must be a string when present")

    sheen_constraint = record.get("sheen_constraint")
    if sheen_constraint is not None and not isinstance(sheen_constraint, str):
        raise UserOverrideError("sheen_constraint must be a string when present")

    geo_override = record.get("geometry_reference_override")
    if geo_override is not None and not isinstance(geo_override, dict):
        raise UserOverrideError("geometry_reference_override must be an object when present")

    role_policy = record.get("input_role_policy")
    if role_policy is not None and not isinstance(role_policy, dict):
        raise UserOverrideError("input_role_policy must be an object when present")

    return record


def load_user_override(path: Path) -> UserOverrideConfig:
    record = json.loads(path.read_text(encoding="utf-8"))
    config = UserOverrideConfig.from_record(record)
    return config


def default_override_path(
    *,
    override_root: Path = DEFAULT_OVERRIDE_ROOT,
    fixture_id: str,
    role: str,
) -> Path:
    return override_root / f"{fixture_id}_{role}.override.json"


def build_user_override_clause(config: UserOverrideConfig) -> str:
    """Render the user-override prompt block.

    When ``prompt_lines`` is set, each entry is emitted verbatim as a bullet in order.
    This supports exact reproduction of reviewed prompt text (hash-stable reuse).
    Otherwise the clause is composed from garment class, reason, requirements, and
    prohibited conversions for simpler future overrides.
    """
    header = "User override (highest precedence):"
    if config.prompt_lines:
        bullets = [f"- {line}" for line in config.prompt_lines]
        return header + "\n" + "\n".join(bullets)

    lines = [
        header,
        f"- Garment class: {config.garment_class}. {config.reason}",
    ]
    lines.extend(f"- {requirement}" for requirement in config.presentation_requirements)
    if config.prohibited_conversions:
        prohibited = ", ".join(config.prohibited_conversions)
        lines.append(f"- Do NOT convert to: {prohibited}.")
    if config.sheen_constraint:
        lines.append(f"- Sheen note: {config.sheen_constraint}")
    return "\n".join(lines)


def serialize_user_override(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"
