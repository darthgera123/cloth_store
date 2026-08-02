"""Deterministic text-retrieval index for the finalized ``final_catalog`` bundle."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloth_store.catalog_display_categories import (
    DISPLAY_CATEGORY_ORDER,
    resolve_display_category,
)
from cloth_store.catalog_exclusions import (
    EXPECTED_CATALOG_ITEM_COUNT,
    EXPECTED_EXCLUDED_OBSERVATION_COUNT,
    ResolvedExclusionMap,
    default_exclusion_registry_path,
    load_exclusion_registry,
    resolve_exclusion_map,
    validate_exclusion_registry,
)
from cloth_store.catalog_garment_identities import (
    EXPECTED_OBSERVATION_COUNT,
    IdentityGroup,
    ObservationEnrichment,
    ResolvedIdentityMap,
    default_registry_path,
    export_garment_identities,
    load_garment_identity_registry,
    resolve_identity_map,
    validate_garment_identity_registry,
    write_garment_identities_export,
)
from cloth_store.catalog_hash import sha256_file
from cloth_store.catalog_paths import CATALOG_ID_ALIASES, CATALOG_ROLE_ORDER, catalog_id
from cloth_store.catalog_user_override import UserOverrideConfig, load_user_override
from cloth_store.catalog_vlm_records import load_extraction_record
from cloth_store.gemini_catalog_generate import sha256_text

CATALOG_INDEX_SCHEMA_VERSION = 2
DEFAULT_FINAL_ROOT = Path("final_catalog")
DEFAULT_CATALOG_JSON = DEFAULT_FINAL_ROOT / "catalog.json"
DEFAULT_GARMENT_IDENTITIES_JSON = DEFAULT_FINAL_ROOT / "garment_identities.json"
DEFAULT_MANIFEST = DEFAULT_FINAL_ROOT / "manifest.json"
EXPECTED_ITEM_COUNT = EXPECTED_CATALOG_ITEM_COUNT

_ABSOLUTE_PATH_PATTERN = re.compile(r"^/|^[A-Za-z]:\\")
_SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

_VLM_FACET_FIELDS: tuple[tuple[str, str], ...] = (
    ("dominant_color", "colors"),
    ("likely_material", "material"),
    ("weave_finish", "finish"),
    ("texture_pattern", "pattern"),
    ("closures_details", "closure"),
    ("surface_sheen", "sheen"),
    ("sleeve_cuff_neckline", "neckline_collar"),
)

_GARMENT_CLASS_ALIASES: dict[str, tuple[str, ...]] = {
    "blouse": ("top", "shirt"),
    "shirt": ("top",),
    "office_blouse": ("blouse", "top"),
    "blazer": ("jacket", "suit jacket"),
    "waistcoat": ("vest", "waist coat"),
    "trousers": ("pants", "trouser"),
    "skirt": ("bottom",),
    "dress": ("one-piece", "one piece"),
}


class CatalogIndexError(ValueError):
    """Raised when catalog index build or validation fails."""


@dataclass(frozen=True)
class ResolvedField:
    value: str | None
    source: str
    confidence: str | None = None
    evidence: str | None = None

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"value": self.value, "source": self.source}
        if self.confidence is not None:
            record["confidence"] = self.confidence
        if self.evidence is not None:
            record["evidence"] = self.evidence
        return record


def serialize_catalog_index(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        raise CatalogIndexError(f"path must be repo-relative: {path}") from None


def _sanitize_repo_path(value: str | None, *, repo_root: Path) -> str | None:
    if value is None:
        return None
    if _ABSOLUTE_PATH_PATTERN.search(value) or _SECRET_PATTERN.search(value):
        raise CatalogIndexError(f"unsafe path or secret-like value in index: {value!r}")
    return value.replace("\\", "/")


def _load_vlm_attributes(case_dir: Path) -> dict[str, dict[str, str]] | None:
    attr_path = case_dir / "attributes.json"
    if not attr_path.is_file():
        return None
    record = load_extraction_record(attr_path)
    attrs = record.get("attributes")
    if not isinstance(attrs, dict):
        return None
    return attrs


def _vlm_field(
    attributes: dict[str, dict[str, str]] | None,
    name: str,
) -> dict[str, str] | None:
    if attributes is None:
        return None
    field = attributes.get(name)
    if not isinstance(field, dict):
        return None
    value = field.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    return field


def _is_unknown_value(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered in {
        "not applicable",
        "none visible",
        "not discernible at this resolution",
        "unknown",
    }


def _prompt_line_text(config: UserOverrideConfig) -> str:
    return " ".join(config.prompt_lines)


def _derive_neckline_from_override(config: UserOverrideConfig) -> ResolvedField:
    combined = _prompt_line_text(config).lower()
    if (
        "structured collar" in combined
        or "structured neckline" in combined
        or "shirt collar" in combined
    ) and "front placket" in combined:
        value = "full sleeves, structured collar, front placket"
        evidence = "user override prompt_lines"
    elif "notched lapel" in combined or "lapel" in combined:
        value = "full sleeves, notched lapel"
        evidence = "user override prompt_lines"
    elif "mock neck" in combined or "high neck" in combined or "high mock" in combined:
        value = "sleeveless high mock neckline"
        evidence = "user override prompt_lines"
    elif "halter" in combined or (
        "sleeveless" in combined and "large" not in combined and "oversized" not in combined
    ):
        value = "sleeveless halter neckline"
        evidence = "user override prompt_lines"
    elif "large" in combined and "collar" in combined:
        value = "sleeveless, large prominent collar neckline"
        evidence = "user override prompt_lines"
    elif "zip" in combined or "zipper" in combined:
        value = "short sleeves, zip-front V neckline"
        evidence = "user override prompt_lines"
    else:
        value = config.reason
        evidence = "user override reason"
    return ResolvedField(
        value=value,
        source="user_override",
        confidence="high",
        evidence=evidence,
    )


def _derive_sheen_from_override(config: UserOverrideConfig) -> ResolvedField | None:
    for line in config.prompt_lines:
        lowered = line.lower()
        if "sheen" not in lowered:
            continue
        match = re.search(
            r"(soft(?:ly)? restrained satin-like sheen|soft satin-like sheen|matte|low sheen)",
            lowered,
        )
        if match:
            return ResolvedField(
                value=match.group(1),
                source="user_override",
                confidence="high",
                evidence=line.strip(),
            )
        if "do not exaggerate" in lowered and "glossy" in lowered:
            return ResolvedField(
                value="soft restrained satin-like sheen",
                source="user_override",
                confidence="high",
                evidence=line.strip(),
            )
    return None


def _resolve_from_vlm(field: dict[str, str] | None) -> ResolvedField | None:
    if field is None:
        return None
    if field.get("confidence") != "high":
        return None
    value = str(field["value"]).strip()
    if _is_unknown_value(value):
        return None
    return ResolvedField(
        value=value,
        source="vlm_high_confidence",
        confidence=str(field.get("confidence")),
        evidence=str(field.get("evidence", "")).strip() or None,
    )


def _resolve_garment_class(
    *,
    override: UserOverrideConfig | None,
    vlm_attrs: dict[str, dict[str, str]] | None,
    template_selection: dict[str, Any],
) -> ResolvedField:
    if override is not None:
        return ResolvedField(
            value=override.garment_class,
            source="user_override",
            confidence="high",
            evidence=override.reason,
        )
    vlm = _resolve_from_vlm(_vlm_field(vlm_attrs, "garment_class"))
    if vlm is not None:
        return vlm
    normalized = template_selection.get("garment_class_normalized")
    if isinstance(normalized, str) and normalized.strip():
        return ResolvedField(
            value=normalized.strip().lower(),
            source="template_selection",
            confidence=str(template_selection.get("confidence")),
            evidence=str(template_selection.get("reason", "")).strip() or None,
        )
    return ResolvedField(value=None, source="unknown")


def _resolve_named_vlm_field(
    *,
    field_name: str,
    override: UserOverrideConfig | None,
    vlm_attrs: dict[str, dict[str, str]] | None,
) -> ResolvedField:
    if override is not None and field_name in override.overridden_vlm_fields:
        if field_name == "sleeve_cuff_neckline":
            return _derive_neckline_from_override(override)
        if field_name == "garment_class":
            return ResolvedField(
                value=override.garment_class,
                source="user_override",
                confidence="high",
                evidence=override.reason,
            )
        return ResolvedField(value=None, source="user_override", confidence="high")

    if field_name == "surface_sheen" and override is not None:
        override_sheen = _derive_sheen_from_override(override)
        if override_sheen is not None:
            return override_sheen

    vlm = _resolve_from_vlm(_vlm_field(vlm_attrs, field_name))
    if vlm is not None:
        return vlm
    return ResolvedField(value=None, source="unknown")


def _resolve_sleeve_length(
    *,
    role: str,
    override: UserOverrideConfig | None,
    vlm_attrs: dict[str, dict[str, str]] | None,
    template_selection: dict[str, Any],
) -> ResolvedField:
    if role not in {"top", "dress"}:
        return ResolvedField(value=None, source="not_applicable")
    if override is not None and "sleeve_cuff_neckline" in override.overridden_vlm_fields:
        combined = _prompt_line_text(override).lower()
        if "sleeveless" in combined or "no sleeves" in combined or "no sleeve" in combined:
            return ResolvedField(value="sleeveless", source="user_override", confidence="high")
        if "full sleeve" in combined or "long sleeve" in combined or "cuffs" in combined:
            return ResolvedField(value="full", source="user_override", confidence="high")
    normalized = template_selection.get("sleeve_length_normalized")
    if isinstance(normalized, str) and normalized.strip():
        return ResolvedField(
            value=normalized.strip().lower(),
            source="template_selection",
            confidence=str(template_selection.get("confidence")),
        )
    neckline = _resolve_named_vlm_field(
        field_name="sleeve_cuff_neckline",
        override=override,
        vlm_attrs=vlm_attrs,
    )
    if neckline.value:
        lowered = neckline.value.lower()
        if "long sleeve" in lowered or "full sleeve" in lowered:
            return ResolvedField(
                value="full",
                source=neckline.source,
                confidence=neckline.confidence,
                evidence=neckline.evidence,
            )
        if "short sleeve" in lowered or "half sleeve" in lowered:
            return ResolvedField(
                value="half",
                source=neckline.source,
                confidence=neckline.confidence,
                evidence=neckline.evidence,
            )
        if "sleeveless" in lowered or "no sleeves" in lowered or "halter" in lowered:
            return ResolvedField(
                value="sleeveless",
                source=neckline.source,
                confidence=neckline.confidence,
                evidence=neckline.evidence,
            )
    return ResolvedField(value=None, source="unknown")


def _resolve_skirt_style(template_selection: dict[str, Any]) -> ResolvedField:
    normalized = template_selection.get("skirt_style_normalized")
    template_id = template_selection.get("template_id")
    if isinstance(normalized, str) and normalized.strip():
        return ResolvedField(
            value=normalized.strip().lower(),
            source="template_selection",
            confidence=str(template_selection.get("confidence")),
            evidence=str(template_selection.get("reason", "")).strip() or None,
        )
    if template_id == "skirt_knee_length":
        return ResolvedField(
            value="knee_length",
            source="template_selection",
            confidence=str(template_selection.get("confidence")),
            evidence="knee-length skirt template",
        )
    if template_id == "skirt_long":
        return ResolvedField(
            value="long",
            source="template_selection",
            confidence=str(template_selection.get("confidence")),
            evidence="long/maxi skirt template",
        )
    return ResolvedField(value=None, source="unknown")


def _sleeveless_top_display_class(garment_class: ResolvedField) -> str | None:
    if not garment_class.value:
        return None
    normalized = garment_class.value.lower().replace(" ", "_")
    if normalized in {"tank_top", "tank"}:
        return "tank top"
    if normalized in {"blouse", "shirt", "office_blouse"}:
        return "sleeveless top"
    return None


def _build_display_name(
    *,
    garment_class: ResolvedField,
    colors: ResolvedField,
    material: ResolvedField,
    skirt_style: ResolvedField,
    sleeve_length: ResolvedField | None = None,
    role: str | None = None,
) -> str:
    parts: list[str] = []
    if colors.value:
        parts.append(colors.value)
    if material.value and not _is_unknown_value(material.value):
        parts.append(material.value)
    if skirt_style.value:
        style_label = {
            "knee_length": "knee-length",
            "long": "long",
            "pencil": "pencil",
            "a_line": "A-line",
        }.get(skirt_style.value, skirt_style.value.replace("_", " "))
        parts.append(f"{style_label} {garment_class.value or 'skirt'}")
    elif garment_class.value:
        sleeveless_class = (
            _sleeveless_top_display_class(garment_class)
            if role == "top" and sleeve_length and sleeve_length.value == "sleeveless"
            else None
        )
        parts.append(sleeveless_class or garment_class.value)
    else:
        parts.append("garment")
    return " ".join(parts)


def _normalize_token(value: str) -> str:
    return _NON_ALNUM.sub(" ", value.lower()).strip()


def _override_search_tags(override: UserOverrideConfig | None) -> set[str]:
    if override is None:
        return set()
    combined = _prompt_line_text(override).lower()
    tags: set[str] = set()
    if "zip" in combined or "zipper" in combined:
        tags.update(
            {
                "zip",
                "zipper",
                "zip top",
                "zip-front",
                "navy zip top",
                "blue zipper v-neck top",
            }
        )
    if "large" in combined and "collar" in combined:
        tags.update(
            {
                "large collar",
                "oversized collar",
                "sleeveless large collar top",
                "lemon print collar blouse",
            }
        )
    if "lemon" in combined:
        tags.update({"lemon print", "lemon print collar blouse"})
    if "floral" in combined:
        tags.update({"floral", "floral print", "floral sleeveless top"})
    if "white" in combined and "button" in combined:
        tags.update({"white shirt", "button-down shirt", "long-sleeve shirt"})
    return tags


def _build_tags(
    *,
    fixture: str,
    role: str,
    garment_class: ResolvedField,
    template_id: str,
    colors: ResolvedField,
    material: ResolvedField,
    pattern: ResolvedField,
    skirt_style: ResolvedField,
    sleeve_length: ResolvedField,
    override: UserOverrideConfig | None = None,
) -> list[str]:
    tags: set[str] = {fixture, role, template_id}
    if garment_class.value:
        sleeveless_class = (
            _sleeveless_top_display_class(garment_class)
            if role == "top" and sleeve_length.value == "sleeveless"
            else None
        )
        if sleeveless_class:
            tags.add(sleeveless_class)
            tags.update({"top", "sleeveless"})
        else:
            tags.add(garment_class.value)
            tags.update(_GARMENT_CLASS_ALIASES.get(garment_class.value, ()))
    if colors.value:
        tags.add(colors.value)
    if material.value and not _is_unknown_value(material.value):
        tags.add(material.value)
    if pattern.value and not _is_unknown_value(pattern.value):
        tags.add(pattern.value)
    if skirt_style.value:
        tags.add(skirt_style.value)
        tags.add(f"{skirt_style.value} skirt")
        if skirt_style.value == "knee_length":
            tags.update({"knee length", "knee-length", "midi", "knee length skirt"})
        elif skirt_style.value == "long":
            tags.update({"long skirt", "maxi", "maxi skirt", "floor length"})
        elif skirt_style.value == "pencil":
            tags.update({"pencil skirt", "straight skirt"})
    if template_id == "skirt_knee_length":
        tags.update({"skirt_knee_length", "knee length skirt"})
    if template_id == "skirt_long":
        tags.update({"skirt_long", "long skirt", "maxi skirt"})
    if template_id == "dress_knee_length_half_sleeve":
        tags.update(
            {
                "dress_knee_length_half_sleeve",
                "knee length dress",
                "knee-length dress",
                "short sleeve dress",
                "half sleeve dress",
                "one-piece dress",
            }
        )
    if sleeve_length.value == "sleeveless":
        tags.add("sleeveless")
    elif sleeve_length.value:
        tags.add(f"{sleeve_length.value} sleeve")
        tags.add(f"{sleeve_length.value} sleeves")
    tags.update(_override_search_tags(override))
    return sorted(tags)


def _build_search_text(
    *,
    display_name: str,
    tags: list[str],
    facets: dict[str, Any],
    template_selection: dict[str, Any],
) -> str:
    chunks: list[str] = [display_name, *tags]
    for key in (
        "colors",
        "material",
        "finish",
        "pattern",
        "sheen",
        "neckline_collar",
        "closure",
        "silhouette_style",
        "sleeve_length",
        "fit",
    ):
        field = facets.get(key)
        if isinstance(field, dict) and field.get("value"):
            chunks.append(str(field["value"]))
    reason = template_selection.get("reason")
    if isinstance(reason, str):
        chunks.append(reason)
    return " ".join(_normalize_token(chunk) for chunk in chunks if chunk)


def _build_item(
    *,
    case: dict[str, Any],
    final_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    fixture = str(case["fixture"])
    role = str(case["role"])
    item_id = catalog_id(fixture, role)
    case_dir = final_root / fixture / role
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.is_file():
        raise CatalogIndexError(f"missing metadata for {item_id}: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    template_selection = metadata.get("template_selection", {})
    if not isinstance(template_selection, dict):
        template_selection = {}

    override: UserOverrideConfig | None = None
    override_rel = metadata.get("source_paths", {}).get("override")
    if metadata.get("user_override_applied") and isinstance(override_rel, str):
        override_path = repo_root / override_rel
        if override_path.is_file():
            override = load_user_override(override_path)

    vlm_attrs = _load_vlm_attributes(case_dir)
    garment_class = _resolve_garment_class(
        override=override,
        vlm_attrs=vlm_attrs,
        template_selection=template_selection,
    )
    colors = _resolve_named_vlm_field(
        field_name="dominant_color",
        override=override,
        vlm_attrs=vlm_attrs,
    )
    material = _resolve_named_vlm_field(
        field_name="likely_material",
        override=override,
        vlm_attrs=vlm_attrs,
    )
    finish = _resolve_named_vlm_field(
        field_name="weave_finish",
        override=override,
        vlm_attrs=vlm_attrs,
    )
    pattern = _resolve_named_vlm_field(
        field_name="texture_pattern",
        override=override,
        vlm_attrs=vlm_attrs,
    )
    sheen = _resolve_named_vlm_field(
        field_name="surface_sheen",
        override=override,
        vlm_attrs=vlm_attrs,
    )
    neckline = _resolve_named_vlm_field(
        field_name="sleeve_cuff_neckline",
        override=override,
        vlm_attrs=vlm_attrs,
    )
    closure = _resolve_named_vlm_field(
        field_name="closures_details",
        override=override,
        vlm_attrs=vlm_attrs,
    )
    sleeve_length = _resolve_sleeve_length(
        role=role,
        override=override,
        vlm_attrs=vlm_attrs,
        template_selection=template_selection,
    )
    skirt_style = _resolve_skirt_style(template_selection)

    silhouette = ResolvedField(value=None, source="unknown")
    if skirt_style.value:
        silhouette = skirt_style
    elif garment_class.value in {"trousers", "pants"}:
        silhouette = ResolvedField(
            value="straight-leg trousers",
            source="template_selection"
            if template_selection.get("template_id") == "pants"
            else "unknown",
            confidence=str(template_selection.get("confidence")),
        )

    facets: dict[str, Any] = {
        "role": {"value": role, "source": "manifest"},
        "garment_class": garment_class.to_record(),
        "colors": colors.to_record(),
        "material": material.to_record(),
        "finish": finish.to_record(),
        "pattern": pattern.to_record(),
        "sheen": sheen.to_record(),
        "neckline_collar": neckline.to_record(),
        "closure": closure.to_record(),
        "sleeve_length": sleeve_length.to_record(),
        "silhouette_style": silhouette.to_record(),
    }

    display_name = _build_display_name(
        garment_class=garment_class,
        colors=colors,
        material=material,
        skirt_style=skirt_style,
        sleeve_length=sleeve_length,
        role=role,
    )
    template_id = str(metadata.get("template_id", template_selection.get("template_id", "")))
    tags = _build_tags(
        fixture=fixture,
        role=role,
        garment_class=garment_class,
        template_id=template_id,
        colors=colors,
        material=material,
        pattern=pattern,
        skirt_style=skirt_style,
        sleeve_length=sleeve_length,
        override=override,
    )
    search_text = _build_search_text(
        display_name=display_name,
        tags=tags,
        facets=facets,
        template_selection=template_selection,
    )

    outputs = metadata.get("outputs", {})
    output_512 = outputs.get("output_512", {})
    output_1k = outputs.get("output_1k", {})
    for label, block in (("output_512", output_512), ("output_1k", output_1k)):
        rel_path = block.get("path")
        expected_sha = block.get("sha256")
        if not isinstance(rel_path, str) or not isinstance(expected_sha, str):
            raise CatalogIndexError(f"{item_id} missing {label} path/sha256 in metadata")
        image_path = final_root / rel_path
        if not image_path.is_file():
            raise CatalogIndexError(f"{item_id} missing image: {image_path}")
        actual_sha = sha256_file(image_path)
        if actual_sha != expected_sha:
            raise CatalogIndexError(
                f"{item_id} hash mismatch for {rel_path}: expected {expected_sha}, got {actual_sha}"
            )

    user_override_block: dict[str, Any] | None = None
    if override is not None:
        user_override_block = {
            "applied": True,
            "garment_class": override.garment_class,
            "reason": override.reason,
            "overridden_vlm_fields": sorted(override.overridden_vlm_fields),
            "namespace": override.namespace,
            "geometry_reference": (
                override.geometry_reference_override.to_artifact_block()
                if override.geometry_reference_override is not None
                else None
            ),
        }

    source_paths = metadata.get("source_paths", {})
    provenance = {
        "model_id": metadata.get("model_id"),
        "prompt_sha256": metadata.get("prompt_sha256"),
        "prompt_policy_version": metadata.get("prompt_policy_version"),
        "metadata_path": f"{fixture}/{role}/metadata.json",
        "artifact_path": _sanitize_repo_path(source_paths.get("artifact"), repo_root=repo_root),
        "vlm_attributes_path": f"{fixture}/{role}/attributes.json"
        if (case_dir / "attributes.json").is_file()
        else None,
        "override_path": _sanitize_repo_path(source_paths.get("override"), repo_root=repo_root),
        "output_512_sha256": output_512.get("sha256"),
        "output_1k_sha256": output_1k.get("sha256"),
        "generated_or_reused": metadata.get("generated_or_reused"),
        "reuse_source": metadata.get("reuse_source"),
        "promoted_from_reference": metadata.get("promoted_from_reference"),
        "promoted_from_candidate": metadata.get("promoted_from_candidate"),
    }

    legacy_catalog_ids = sorted(
        alias_id for alias_id, canonical_id in CATALOG_ID_ALIASES.items() if canonical_id == item_id
    )

    item_record: dict[str, Any] = {
        "catalog_id": item_id,
        "fixture": fixture,
        "role": role,
        "display_name": display_name,
        "garment_class_normalized": garment_class.value,
        "garment_subtype": skirt_style.value,
        "images": {
            "output_512": {
                "path": output_512["path"],
                "sha256": output_512["sha256"],
            },
            "output_1k": {
                "path": output_1k["path"],
                "sha256": output_1k["sha256"],
            },
        },
        "template": {
            "template_id": template_id,
            "selection_confidence": template_selection.get("confidence"),
            "selection_reason": template_selection.get("reason"),
            "override_applied": bool(template_selection.get("override_applied")),
        },
        "user_override": user_override_block,
        "facets": facets,
        "tags": tags,
        "retrieval": {
            "search_text": search_text,
            "lexical_only": True,
        },
        "provenance": provenance,
    }
    if legacy_catalog_ids:
        item_record["legacy_catalog_ids"] = legacy_catalog_ids
        alias_search = " ".join(_normalize_token(alias) for alias in legacy_catalog_ids)
        item_record["retrieval"]["search_text"] = f"{search_text} {alias_search}".strip()
    item_record["display_category"] = resolve_display_category(
        role=role,
        garment_class_normalized=garment_class.value,
    )
    return item_record


def _segmented_input_record(
    *,
    case_dir: Path,
    fixture: str,
    role: str,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    for record in metadata.get("packaged_inputs", []):
        if not isinstance(record, dict):
            continue
        if record.get("role") != "garment_identity":
            continue
        filename = record.get("filename")
        sha = record.get("sha256")
        if not isinstance(filename, str) or not isinstance(sha, str):
            return None
        return {
            "path": f"{fixture}/{role}/{filename}",
            "sha256": sha,
        }
    return None


def _source_observation_record(
    *,
    item: dict[str, Any],
    final_root: Path,
    indexed: bool,
    canonical: bool,
) -> dict[str, Any]:
    fixture = str(item["fixture"])
    role = str(item["role"])
    observation_id = str(item["catalog_id"])
    case_dir = final_root / fixture / role
    metadata_path = case_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    attributes_rel = f"{fixture}/{role}/attributes.json"
    attributes_path = attributes_rel if (case_dir / "attributes.json").is_file() else None
    segmented = _segmented_input_record(
        case_dir=case_dir,
        fixture=fixture,
        role=role,
        metadata=metadata,
    )
    images: dict[str, Any] = {
        "output_512": dict(item["images"]["output_512"]),
        "output_1k": dict(item["images"]["output_1k"]),
    }
    if segmented is not None:
        images["input_segmented"] = segmented
    return {
        "observation_id": observation_id,
        "fixture": fixture,
        "role": role,
        "indexed": indexed,
        "canonical": canonical,
        "display_name": item.get("display_name"),
        "metadata_path": f"{fixture}/{role}/metadata.json",
        "attributes_path": attributes_path,
        "images": images,
        "tags": list(item.get("tags", [])),
        "provenance": dict(item.get("provenance", {})),
    }


def _merge_tags(*tag_lists: list[str]) -> list[str]:
    merged: set[str] = set()
    for tags in tag_lists:
        merged.update(tags)
    return sorted(merged)


def _apply_facet_corrections(
    *,
    facets: dict[str, Any],
    group: IdentityGroup,
) -> dict[str, Any]:
    updated = json.loads(json.dumps(facets))
    corrections = group.facet_corrections or {}
    colors = corrections.get("colors")
    if isinstance(colors, list) and colors:
        primary = str(colors[0]).strip()
        if primary:
            updated["colors"] = {
                "value": primary,
                "source": "user_confirmed_identity",
                "confidence": "high",
                "evidence": group.notes or group.reason,
            }
    fit = corrections.get("fit")
    if isinstance(fit, str) and fit.strip():
        updated["fit"] = {
            "value": fit.strip().lower(),
            "source": "user_confirmed_identity",
            "confidence": "high",
            "evidence": group.notes or group.reason,
        }
    return updated


def _apply_observation_enrichment(
    *,
    item: dict[str, Any],
    enrichment: ObservationEnrichment,
) -> dict[str, Any]:
    updated = json.loads(json.dumps(item))
    corrections = enrichment.facet_corrections or {}
    facets = updated["facets"]
    fit = corrections.get("fit")
    if isinstance(fit, str) and fit.strip():
        facets["fit"] = {
            "value": fit.strip().lower(),
            "source": "user_confirmed",
            "confidence": "high",
            "evidence": enrichment.notes or enrichment.reason,
        }
    colors = corrections.get("colors")
    stale_color_tags = corrections.get("stale_color_tags")
    previous_color = (facets.get("colors") or {}).get("value")
    if isinstance(colors, list) and colors:
        primary = str(colors[0]).strip()
        if primary:
            color_source = (
                "user_confirmed" if enrichment.reason == "user_confirmed" else enrichment.reason
            )
            facets["colors"] = {
                "value": primary,
                "source": color_source,
                "confidence": "high",
                "evidence": enrichment.notes or enrichment.reason,
            }
    updated["facets"] = facets

    tags = list(updated.get("tags", []))
    if isinstance(colors, list) and colors:
        color_tags = [str(color).strip() for color in colors if str(color).strip()]
        garment_class_label = updated.get("garment_class_normalized") or "garment"
        remove_tags = {
            str(tag).strip().lower()
            for tag in (
                ([previous_color] if previous_color else [])
                + (stale_color_tags if isinstance(stale_color_tags, list) else [])
            )
            if str(tag).strip()
        }
        tags = [
            tag
            for tag in tags
            if tag.strip().lower() not in remove_tags
            and not any(
                tag.strip().lower() == f"{stale} {garment_class_label}" for stale in remove_tags
            )
        ]
        tags = _merge_tags(
            tags,
            color_tags + [f"{color} {garment_class_label}" for color in color_tags],
        )
    elif isinstance(stale_color_tags, list) and stale_color_tags:
        garment_class_label = updated.get("garment_class_normalized") or "garment"
        remove_tags = {str(tag).strip().lower() for tag in stale_color_tags if str(tag).strip()}
        tags = [
            tag
            for tag in tags
            if tag.strip().lower() not in remove_tags
            and not any(
                tag.strip().lower() == f"{stale} {garment_class_label}" for stale in remove_tags
            )
        ]
    if isinstance(fit, str) and fit.strip():
        fit_label = fit.strip().lower()
        garment_class_label = updated.get("garment_class_normalized") or "trousers"
        tags = _merge_tags(
            tags,
            [
                fit_label,
                f"{fit_label} fit",
                f"{fit_label} fit trousers",
                f"{fit_label} fit {garment_class_label}",
            ],
        )
    updated["tags"] = tags

    display_name = enrichment.display_name or updated.get("display_name")
    if display_name:
        updated["display_name"] = display_name
    search_text = _build_search_text(
        display_name=str(updated["display_name"]),
        tags=tags,
        facets=facets,
        template_selection=updated["template"],
    )
    updated["search_text"] = search_text
    retrieval = updated.get("retrieval")
    if isinstance(retrieval, dict):
        retrieval = dict(retrieval)
        retrieval["search_text"] = search_text
        updated["retrieval"] = retrieval
    return updated


def _merge_identity_group(
    *,
    group: IdentityGroup,
    observation_items: dict[str, dict[str, Any]],
    final_root: Path,
) -> dict[str, Any]:
    canonical_item = observation_items[group.canonical_observation_id]
    merged_item = json.loads(json.dumps(canonical_item))
    source_observations: list[dict[str, Any]] = []

    for observation_id in group.observation_ids:
        item = observation_items[observation_id]
        source_observations.append(
            _source_observation_record(
                item=item,
                final_root=final_root,
                indexed=observation_id == group.canonical_observation_id,
                canonical=observation_id == group.canonical_observation_id,
            )
        )

    merged_tags = _merge_tags(
        *[observation_items[observation_id]["tags"] for observation_id in group.observation_ids]
    )
    corrections = group.facet_corrections or {}
    color_tags = corrections.get("colors")
    stale_color_tags = corrections.get("stale_color_tags")
    previous_color = (merged_item.get("facets", {}).get("colors") or {}).get("value")
    garment_class_label = merged_item.get("garment_class_normalized") or "garment"
    if isinstance(color_tags, list) or isinstance(stale_color_tags, list):
        remove_tags = {
            str(tag).strip().lower()
            for tag in (
                ([previous_color] if previous_color else [])
                + (stale_color_tags if isinstance(stale_color_tags, list) else [])
            )
            if str(tag).strip()
        }
        merged_tags = [
            tag
            for tag in merged_tags
            if tag.strip().lower() not in remove_tags
            and not any(
                tag.strip().lower() == f"{stale} {garment_class_label}" for stale in remove_tags
            )
        ]
        if isinstance(color_tags, list):
            color_tag_list = [str(color).strip() for color in color_tags if str(color).strip()]
            merged_tags = _merge_tags(
                merged_tags,
                color_tag_list + [f"{color} {garment_class_label}" for color in color_tag_list],
            )
    fit = corrections.get("fit")
    if isinstance(fit, str) and fit.strip():
        fit_label = fit.strip().lower()
        merged_tags = _merge_tags(
            merged_tags,
            [
                fit_label,
                f"{fit_label} fit",
                f"{fit_label} fit trousers",
                f"{fit_label} fit {merged_item.get('garment_class_normalized') or 'trousers'}",
            ],
        )
    for observation_id in group.observation_ids:
        fixture, role = observation_id.rsplit("_", 1)
        merged_tags = _merge_tags(
            merged_tags,
            [observation_id, fixture, role.replace("_", " ")],
        )

    facets = _apply_facet_corrections(facets=merged_item["facets"], group=group)
    display_name = group.display_name or merged_item["display_name"]
    if group.display_name:
        merged_tags = _merge_tags(merged_tags, [group.display_name])
    search_text = _build_search_text(
        display_name=display_name,
        tags=merged_tags,
        facets=facets,
        template_selection=merged_item["template"],
    )

    merged_item.update(
        {
            "catalog_id": group.canonical_observation_id,
            "garment_id": group.garment_id,
            "canonical_observation_id": group.canonical_observation_id,
            "observation_ids": list(group.observation_ids),
            "alias_observation_ids": list(group.alias_observation_ids),
            "display_name": display_name,
            "facets": facets,
            "tags": merged_tags,
            "retrieval": {
                "search_text": search_text,
                "lexical_only": True,
            },
            "identity": {
                "reason": group.reason,
                "notes": group.notes,
                "canonical_selection_reason": group.canonical_selection_reason,
                "merged_observation_count": len(group.observation_ids),
                "alias_color_tokens": [
                    str(color).lower()
                    for color in (color_tags if isinstance(color_tags, list) else [])
                    if str(color).strip()
                ],
            },
            "source_observations": source_observations,
        }
    )
    return merged_item


def _apply_identity_deduplication(
    *,
    observation_items: list[dict[str, Any]],
    identity_map: ResolvedIdentityMap,
    exclusion_map: ResolvedExclusionMap,
    final_root: Path,
) -> list[dict[str, Any]]:
    by_observation = {str(item["catalog_id"]): item for item in observation_items}
    if len(by_observation) != EXPECTED_OBSERVATION_COUNT:
        raise CatalogIndexError(
            f"expected {EXPECTED_OBSERVATION_COUNT} observation items, got {len(by_observation)}"
        )

    merged_groups = {group.garment_id: group for group in identity_map.groups}
    emitted_garments: set[str] = set()
    unique_items: list[dict[str, Any]] = []

    for observation_id in sorted(by_observation.keys()):
        if observation_id in exclusion_map.excluded_observations:
            continue
        garment_id = identity_map.observation_to_garment[observation_id]
        if garment_id in emitted_garments:
            continue
        if garment_id in merged_groups:
            unique_items.append(
                _merge_identity_group(
                    group=merged_groups[garment_id],
                    observation_items=by_observation,
                    final_root=final_root,
                )
            )
        else:
            item = json.loads(json.dumps(by_observation[observation_id]))
            item["garment_id"] = garment_id
            item["canonical_observation_id"] = observation_id
            item["observation_ids"] = [observation_id]
            item["alias_observation_ids"] = []
            item["source_observations"] = [
                _source_observation_record(
                    item=item,
                    final_root=final_root,
                    indexed=True,
                    canonical=True,
                )
            ]
            enrichment = identity_map.observation_enrichments.get(observation_id)
            if enrichment is not None:
                item = _apply_observation_enrichment(item=item, enrichment=enrichment)
            unique_items.append(item)
        emitted_garments.add(garment_id)

    unique_items.sort(key=lambda row: row["catalog_id"])
    if len(unique_items) != EXPECTED_ITEM_COUNT:
        raise CatalogIndexError(
            f"expected {EXPECTED_ITEM_COUNT} unique garment items, got {len(unique_items)}"
        )
    return unique_items


def _build_summary(
    items: list[dict[str, Any]],
    *,
    exclusion_map: ResolvedExclusionMap,
) -> dict[str, Any]:
    roles: set[str] = set()
    classes: set[str] = set()
    colors: set[str] = set()
    materials: set[str] = set()
    templates: set[str] = set()
    sections: dict[str, list[str]] = {role: [] for role in CATALOG_ROLE_ORDER}
    role_counts: dict[str, int] = {}
    display_sections: dict[str, list[str]] = {category: [] for category in DISPLAY_CATEGORY_ORDER}
    display_category_counts: dict[str, int] = {}
    overrides = 0
    merged_identities = 0
    for item in items:
        role = str(item["role"])
        roles.add(role)
        sections.setdefault(role, []).append(str(item["catalog_id"]))
        role_counts[role] = role_counts.get(role, 0) + 1
        display_category = str(item.get("display_category", role))
        display_sections.setdefault(display_category, []).append(str(item["catalog_id"]))
        display_category_counts[display_category] = (
            display_category_counts.get(display_category, 0) + 1
        )
        if item.get("garment_class_normalized"):
            classes.add(str(item["garment_class_normalized"]))
        colors_field = item["facets"]["colors"]
        if colors_field.get("value"):
            colors.add(str(colors_field["value"]))
        material_field = item["facets"]["material"]
        if material_field.get("value") and not _is_unknown_value(str(material_field["value"])):
            materials.add(str(material_field["value"]))
        templates.add(str(item["template"]["template_id"]))
        if item.get("user_override"):
            overrides += 1
        if len(item.get("observation_ids", [])) > 1:
            merged_identities += 1
    return {
        "observation_count": EXPECTED_OBSERVATION_COUNT,
        "excluded_observation_count": len(exclusion_map.excluded_observations),
        "unique_garment_count": len(items),
        "total_items": len(items),
        "merged_identity_count": merged_identities,
        "user_override_count": overrides,
        "facets": {
            "roles": sorted(roles),
            "garment_classes": sorted(classes),
            "colors": sorted(colors),
            "materials": sorted(materials),
            "template_ids": sorted(templates),
        },
        "sections": {
            role: sorted(members) for role, members in sorted(sections.items()) if members
        },
        "role_counts": dict(sorted(role_counts.items())),
        "display_sections": {
            category: sorted(members)
            for category, members in sorted(display_sections.items())
            if members
        },
        "display_category_counts": dict(sorted(display_category_counts.items())),
    }


def build_catalog_index(
    *,
    repo_root: Path,
    final_root: Path = DEFAULT_FINAL_ROOT,
    registry_path: Path | None = None,
    exclusion_registry_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = final_root / "manifest.json"
    if not manifest_path.is_file():
        raise CatalogIndexError(f"missing final catalog manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])
    if not isinstance(cases, list):
        raise CatalogIndexError("manifest cases must be a list")

    observation_items = [
        _build_item(case=case, final_root=final_root, repo_root=repo_root)
        for case in sorted(cases, key=lambda row: (row["fixture"], row["role"]))
    ]

    resolved_registry = registry_path or default_registry_path(repo_root)
    registry_payload = load_garment_identity_registry(resolved_registry)
    identity_map = validate_garment_identity_registry(
        payload=registry_payload,
        final_root=final_root,
        repo_root=repo_root,
    )
    resolved_exclusions = exclusion_registry_path or default_exclusion_registry_path(repo_root)
    exclusion_payload = load_exclusion_registry(resolved_exclusions)
    exclusion_map = validate_exclusion_registry(
        payload=exclusion_payload,
        final_root=final_root,
        identity_map=identity_map,
    )
    items = _apply_identity_deduplication(
        observation_items=observation_items,
        identity_map=identity_map,
        exclusion_map=exclusion_map,
        final_root=final_root,
    )

    validate_catalog_index(
        payload={"items": items},
        final_root=final_root,
        repo_root=repo_root,
        identity_map=identity_map,
        exclusion_map=exclusion_map,
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    registry_text = resolved_registry.read_text(encoding="utf-8")
    exclusion_text = resolved_exclusions.read_text(encoding="utf-8")
    return {
        "schema_version": CATALOG_INDEX_SCHEMA_VERSION,
        "namespace": manifest.get("namespace", "catalog_production_v1"),
        "source_snapshot": {
            "manifest_schema_version": manifest.get("schema_version"),
            "manifest_packaged_at_utc": manifest.get("packaged_at_utc"),
            "manifest_sha256": sha256_text(manifest_text),
            "final_catalog_root": _repo_relative(final_root, repo_root),
            "garment_identity_registry_path": _repo_relative(resolved_registry, repo_root),
            "garment_identity_registry_sha256": sha256_text(registry_text),
            "catalog_exclusion_registry_path": _repo_relative(resolved_exclusions, repo_root),
            "catalog_exclusion_registry_sha256": sha256_text(exclusion_text),
        },
        "summary": _build_summary(items, exclusion_map=exclusion_map),
        "items": items,
    }


def validate_catalog_index(
    *,
    payload: dict[str, Any],
    final_root: Path,
    repo_root: Path,
    identity_map: ResolvedIdentityMap | None = None,
    exclusion_map: ResolvedExclusionMap | None = None,
) -> None:
    items = payload.get("items")
    if not isinstance(items, list):
        raise CatalogIndexError("catalog index items must be a list")
    if len(items) != EXPECTED_ITEM_COUNT:
        raise CatalogIndexError(f"expected {EXPECTED_ITEM_COUNT} items, got {len(items)}")

    summary = payload.get("summary")
    if isinstance(summary, dict):
        if summary.get("observation_count") != EXPECTED_OBSERVATION_COUNT:
            raise CatalogIndexError(
                f"expected observation_count={EXPECTED_OBSERVATION_COUNT}, "
                f"got {summary.get('observation_count')}"
            )
        if summary.get("unique_garment_count") != EXPECTED_ITEM_COUNT:
            raise CatalogIndexError(
                f"expected unique_garment_count={EXPECTED_ITEM_COUNT}, "
                f"got {summary.get('unique_garment_count')}"
            )
        if summary.get("excluded_observation_count") != EXPECTED_EXCLUDED_OBSERVATION_COUNT:
            raise CatalogIndexError(
                f"expected excluded_observation_count={EXPECTED_EXCLUDED_OBSERVATION_COUNT}, "
                f"got {summary.get('excluded_observation_count')}"
            )

    ids = [item.get("catalog_id") for item in items]
    if len(set(ids)) != len(ids):
        raise CatalogIndexError("catalog_id values must be unique")
    if sorted(ids) != ids:
        raise CatalogIndexError("items must be sorted by catalog_id")

    garment_ids = [item.get("garment_id") for item in items]
    if any(not isinstance(garment_id, str) or not garment_id for garment_id in garment_ids):
        raise CatalogIndexError("each item requires garment_id")
    if len(set(garment_ids)) != len(garment_ids):
        raise CatalogIndexError("garment_id values must be unique")

    if identity_map is not None:
        indexed_ids = set(ids)
        for group in identity_map.groups:
            if group.canonical_observation_id not in indexed_ids:
                raise CatalogIndexError(
                    f"canonical observation {group.canonical_observation_id!r} must be indexed"
                )
            for alias_id in group.alias_observation_ids:
                if alias_id in indexed_ids:
                    raise CatalogIndexError(f"alias observation {alias_id!r} must not be indexed")
        if len(indexed_ids) != EXPECTED_ITEM_COUNT:
            raise CatalogIndexError(
                f"expected {EXPECTED_ITEM_COUNT} indexed catalog items, got {len(indexed_ids)}"
            )
    if exclusion_map is not None:
        indexed_ids = {str(item["catalog_id"]) for item in items}
        overlap = indexed_ids.intersection(exclusion_map.excluded_observations)
        if overlap:
            raise CatalogIndexError(f"excluded observations must not be indexed: {sorted(overlap)}")

    for item in items:
        if not isinstance(item.get("display_category"), str):
            raise CatalogIndexError(f"{item.get('catalog_id')!r} missing display_category")
        expected_category = resolve_display_category(
            role=str(item.get("role", "")),
            garment_class_normalized=item.get("garment_class_normalized"),
        )
        if item["display_category"] != expected_category:
            raise CatalogIndexError(
                f"{item.get('catalog_id')!r} display_category="
                f"{item['display_category']!r} expected {expected_category!r}"
            )
        if item["display_category"] == "blazer" and item.get("role") != "top":
            raise CatalogIndexError(
                f"{item.get('catalog_id')!r} blazer display_category requires role=top"
            )

    serialized = serialize_catalog_index(payload)
    if _SECRET_PATTERN.search(serialized):
        raise CatalogIndexError("catalog index must not contain secret-like values")
    if _ABSOLUTE_PATH_PATTERN.search(serialized):
        raise CatalogIndexError("catalog index must not contain absolute paths")

    for item in items:
        catalog_id_value = item.get("catalog_id")
        if not isinstance(catalog_id_value, str):
            raise CatalogIndexError("each item requires catalog_id")
        for image_key in ("output_512", "output_1k"):
            image = item.get("images", {}).get(image_key, {})
            rel_path = image.get("path")
            expected_sha = image.get("sha256")
            if not isinstance(rel_path, str) or not isinstance(expected_sha, str):
                raise CatalogIndexError(
                    f"{catalog_id_value} missing image metadata for {image_key}"
                )
            image_path = final_root / rel_path
            if not image_path.is_file():
                raise CatalogIndexError(f"{catalog_id_value} missing file: {image_path}")
            actual_sha = sha256_file(image_path)
            if actual_sha != expected_sha:
                raise CatalogIndexError(
                    f"{catalog_id_value} stale hash for {rel_path}: "
                    f"expected {expected_sha}, got {actual_sha}"
                )
        retrieval = item.get("retrieval", {})
        if (
            not isinstance(retrieval.get("search_text"), str)
            or not retrieval["search_text"].strip()
        ):
            raise CatalogIndexError(f"{catalog_id_value} missing retrieval.search_text")
        source_observations = item.get("source_observations")
        if not isinstance(source_observations, list) or not source_observations:
            raise CatalogIndexError(f"{catalog_id_value} missing source_observations")


def write_catalog_index(
    *,
    repo_root: Path,
    final_root: Path = DEFAULT_FINAL_ROOT,
    output_path: Path = DEFAULT_CATALOG_JSON,
    registry_path: Path | None = None,
    identities_output_path: Path = DEFAULT_GARMENT_IDENTITIES_JSON,
) -> Path:
    payload = build_catalog_index(
        repo_root=repo_root,
        final_root=final_root,
        registry_path=registry_path,
    )
    identity_map = resolve_identity_map(
        repo_root=repo_root,
        final_root=final_root,
        registry_path=registry_path,
    )
    exclusion_map = resolve_exclusion_map(
        repo_root=repo_root,
        final_root=final_root,
        identity_registry_path=registry_path,
    )
    validate_catalog_index(
        payload=payload,
        final_root=final_root,
        repo_root=repo_root,
        identity_map=identity_map,
        exclusion_map=exclusion_map,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_catalog_index(payload), encoding="utf-8")

    resolved_registry = registry_path or default_registry_path(repo_root)
    manifest = json.loads((final_root / "manifest.json").read_text(encoding="utf-8"))
    identities_payload = export_garment_identities(
        identity_map=identity_map,
        manifest=manifest,
        registry_path=resolved_registry,
        repo_root=repo_root,
        final_root=final_root,
        excluded_observations=exclusion_map.excluded_observations,
    )
    identities_path = identities_output_path
    if not identities_path.is_absolute():
        identities_path = repo_root / identities_path
    write_garment_identities_export(payload=identities_payload, output_path=identities_path)
    return output_path


def load_catalog_index(path: Path = DEFAULT_CATALOG_JSON) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or validate final catalog text index.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory)",
    )
    parser.add_argument(
        "--final-root",
        type=Path,
        default=DEFAULT_FINAL_ROOT,
        help="Final catalog directory relative to repo root",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CATALOG_JSON,
        help="Output catalog.json path relative to repo root",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate an existing catalog.json without rewriting",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    final_root = (repo_root / args.final_root).resolve()
    output_path = (repo_root / args.output).resolve()

    try:
        if args.validate_only:
            if not output_path.is_file():
                raise CatalogIndexError(f"missing catalog index: {output_path}")
            payload = load_catalog_index(output_path)
            identity_map = resolve_identity_map(repo_root=repo_root, final_root=final_root)
            exclusion_map = resolve_exclusion_map(repo_root=repo_root, final_root=final_root)
            validate_catalog_index(
                payload=payload,
                final_root=final_root,
                repo_root=repo_root,
                identity_map=identity_map,
                exclusion_map=exclusion_map,
            )
            print(f"validated {output_path} ({len(payload['items'])} items)")
            return 0

        path = write_catalog_index(
            repo_root=repo_root,
            final_root=final_root,
            output_path=output_path,
        )
        print(
            f"wrote {path} ({EXPECTED_ITEM_COUNT} unique garments, "
            f"{EXPECTED_OBSERVATION_COUNT} observations)"
        )
        return 0
    except CatalogIndexError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
