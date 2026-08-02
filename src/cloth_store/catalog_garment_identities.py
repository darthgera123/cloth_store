"""User-confirmed garment identity registry for catalog deduplication."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloth_store.catalog_paths import catalog_id
from cloth_store.gemini_catalog_generate import sha256_text

DEFAULT_REGISTRY_PATH = Path("bench/catalog_generation/garment_identities.json")
DEFAULT_FINAL_ROOT = Path("final_catalog")
DEFAULT_MANIFEST = DEFAULT_FINAL_ROOT / "manifest.json"
DEFAULT_EXPORT_PATH = DEFAULT_FINAL_ROOT / "garment_identities.json"

GARMENT_ID_PATTERN = re.compile(r"^garment_[a-z0-9_]+$")
OBSERVATION_ID_PATTERN = re.compile(r"^outfit_\d+_(top|bottom|dress)$")

EXPECTED_OBSERVATION_COUNT = 59
EXPECTED_UNIQUE_GARMENT_COUNT = 37


class GarmentIdentityError(ValueError):
    """Raised when garment identity registry validation or resolution fails."""


@dataclass(frozen=True)
class IdentityGroup:
    garment_id: str
    canonical_observation_id: str
    observation_ids: tuple[str, ...]
    reason: str
    display_name: str | None = None
    facet_corrections: dict[str, Any] | None = None
    notes: str | None = None
    canonical_selection_reason: str | None = None

    @property
    def alias_observation_ids(self) -> tuple[str, ...]:
        return tuple(
            observation_id
            for observation_id in self.observation_ids
            if observation_id != self.canonical_observation_id
        )


@dataclass(frozen=True)
class ObservationEnrichment:
    observation_id: str
    reason: str
    facet_corrections: dict[str, Any] | None = None
    display_name: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ResolvedIdentityMap:
    groups: tuple[IdentityGroup, ...]
    observation_to_garment: dict[str, str]
    canonical_by_garment: dict[str, str]
    alias_observations: frozenset[str]
    default_garment_ids: dict[str, str]
    observation_enrichments: dict[str, ObservationEnrichment]


def serialize_registry(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def default_registry_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_REGISTRY_PATH


def load_garment_identity_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise GarmentIdentityError(f"missing garment identity registry: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GarmentIdentityError("garment identity registry must be a JSON object")
    return payload


def _parse_observation_id(observation_id: str) -> tuple[str, str]:
    if not OBSERVATION_ID_PATTERN.fullmatch(observation_id):
        raise GarmentIdentityError(f"invalid observation id: {observation_id!r}")
    fixture, role = observation_id.rsplit("_", 1)
    return fixture, role


def _parse_group(raw: dict[str, Any]) -> IdentityGroup:
    garment_id = raw.get("garment_id")
    canonical_observation_id = raw.get("canonical_observation_id")
    observation_ids = raw.get("observation_ids")
    reason = raw.get("reason")

    if not isinstance(garment_id, str) or not GARMENT_ID_PATTERN.fullmatch(garment_id):
        raise GarmentIdentityError(f"invalid garment_id: {garment_id!r}")
    if not isinstance(canonical_observation_id, str):
        raise GarmentIdentityError("group requires canonical_observation_id")
    if not isinstance(observation_ids, list) or len(observation_ids) < 2:
        raise GarmentIdentityError(f"group {garment_id} requires at least two observation_ids")
    if reason != "user_confirmed":
        raise GarmentIdentityError(
            f"group {garment_id} reason must be user_confirmed, got {reason!r}"
        )

    parsed_ids = tuple(str(item) for item in observation_ids)
    for observation_id in parsed_ids:
        _parse_observation_id(observation_id)
    if canonical_observation_id not in parsed_ids:
        raise GarmentIdentityError(
            f"group {garment_id}: canonical_observation_id "
            f"{canonical_observation_id!r} must be listed in observation_ids"
        )
    if len(set(parsed_ids)) != len(parsed_ids):
        raise GarmentIdentityError(f"group {garment_id}: duplicate observation_ids")

    display_name = raw.get("display_name")
    if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
        raise GarmentIdentityError(f"group {garment_id}: display_name must be non-empty text")

    facet_corrections = raw.get("facet_corrections")
    if facet_corrections is not None and not isinstance(facet_corrections, dict):
        raise GarmentIdentityError(f"group {garment_id}: facet_corrections must be an object")

    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise GarmentIdentityError(f"group {garment_id}: notes must be text")

    canonical_selection_reason = raw.get("canonical_selection_reason")
    if canonical_selection_reason is not None and not isinstance(canonical_selection_reason, str):
        raise GarmentIdentityError(f"group {garment_id}: canonical_selection_reason must be text")

    return IdentityGroup(
        garment_id=garment_id,
        canonical_observation_id=canonical_observation_id,
        observation_ids=parsed_ids,
        reason=reason,
        display_name=display_name.strip() if isinstance(display_name, str) else None,
        facet_corrections=facet_corrections,
        notes=notes,
        canonical_selection_reason=canonical_selection_reason,
    )


def parse_identity_groups(payload: dict[str, Any]) -> tuple[IdentityGroup, ...]:
    groups_raw = payload.get("groups")
    if not isinstance(groups_raw, list):
        raise GarmentIdentityError("registry groups must be a list")

    groups = [_parse_group(group) for group in groups_raw if isinstance(group, dict)]
    garment_ids = [group.garment_id for group in groups]
    if len(set(garment_ids)) != len(garment_ids):
        raise GarmentIdentityError("garment_id values must be unique across groups")
    return tuple(groups)


def _parse_observation_enrichment(raw: dict[str, Any]) -> ObservationEnrichment:
    observation_id = raw.get("observation_id")
    reason = raw.get("reason")
    if not isinstance(observation_id, str):
        raise GarmentIdentityError("observation enrichment requires observation_id")
    _parse_observation_id(observation_id)
    if reason not in {"user_confirmed", "reviewed_cutout_evidence"}:
        raise GarmentIdentityError(
            f"observation enrichment {observation_id}: "
            f"reason must be user_confirmed or reviewed_cutout_evidence, got {reason!r}"
        )
    facet_corrections = raw.get("facet_corrections")
    if facet_corrections is not None and not isinstance(facet_corrections, dict):
        raise GarmentIdentityError(
            f"observation enrichment {observation_id}: facet_corrections must be an object"
        )
    display_name = raw.get("display_name")
    if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
        raise GarmentIdentityError(
            f"observation enrichment {observation_id}: display_name must be non-empty text"
        )
    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise GarmentIdentityError(f"observation enrichment {observation_id}: notes must be text")
    return ObservationEnrichment(
        observation_id=observation_id,
        reason=reason,
        facet_corrections=facet_corrections,
        display_name=display_name.strip() if isinstance(display_name, str) else None,
        notes=notes,
    )


def parse_observation_enrichments(payload: dict[str, Any]) -> dict[str, ObservationEnrichment]:
    enrichments_raw = payload.get("observation_enrichments")
    if enrichments_raw is None:
        return {}
    if not isinstance(enrichments_raw, list):
        raise GarmentIdentityError("observation_enrichments must be a list")
    enrichments: dict[str, ObservationEnrichment] = {}
    for raw in enrichments_raw:
        if not isinstance(raw, dict):
            raise GarmentIdentityError("observation_enrichments entries must be objects")
        enrichment = _parse_observation_enrichment(raw)
        if enrichment.observation_id in enrichments:
            raise GarmentIdentityError(
                f"duplicate observation enrichment for {enrichment.observation_id!r}"
            )
        enrichments[enrichment.observation_id] = enrichment
    return enrichments


def _load_manifest_cases(final_root: Path) -> list[dict[str, Any]]:
    manifest_path = final_root / "manifest.json"
    if not manifest_path.is_file():
        raise GarmentIdentityError(f"missing final catalog manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])
    if not isinstance(cases, list):
        raise GarmentIdentityError("manifest cases must be a list")
    return cases


def _manifest_observation_ids(cases: list[dict[str, Any]]) -> set[str]:
    observation_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            continue
        fixture = case.get("fixture")
        role = case.get("role")
        if isinstance(fixture, str) and isinstance(role, str):
            observation_ids.add(catalog_id(fixture, role))
    return observation_ids


def _observation_garment_class(final_root: Path, observation_id: str) -> str | None:
    fixture, role = _parse_observation_id(observation_id)
    metadata_path = final_root / fixture / role / "metadata.json"
    if not metadata_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    template_selection = metadata.get("template_selection", {})
    if isinstance(template_selection, dict):
        normalized = template_selection.get("garment_class_normalized")
        if isinstance(normalized, str) and normalized.strip():
            return normalized.strip().lower()
    return None


def validate_garment_identity_registry(
    *,
    payload: dict[str, Any],
    final_root: Path,
    repo_root: Path,
    cases: list[dict[str, Any]] | None = None,
) -> ResolvedIdentityMap:
    del repo_root  # reserved for future repo-relative checks
    if payload.get("schema_version") != 1:
        raise GarmentIdentityError("registry schema_version must be 1")

    groups = parse_identity_groups(payload)
    observation_enrichments = parse_observation_enrichments(payload)
    resolved_cases = cases if cases is not None else _load_manifest_cases(final_root)
    manifest_ids = _manifest_observation_ids(resolved_cases)
    if len(manifest_ids) != EXPECTED_OBSERVATION_COUNT:
        raise GarmentIdentityError(
            f"expected {EXPECTED_OBSERVATION_COUNT} manifest observations, got {len(manifest_ids)}"
        )

    assigned: dict[str, str] = {}
    observation_to_garment: dict[str, str] = {}
    canonical_by_garment: dict[str, str] = {}
    alias_observations: set[str] = set()

    for group in groups:
        roles: set[str] = set()
        classes: set[str] = set()
        for observation_id in group.observation_ids:
            if observation_id not in manifest_ids:
                raise GarmentIdentityError(
                    f"unknown observation id {observation_id!r} in group {group.garment_id}"
                )
            if observation_id in assigned:
                raise GarmentIdentityError(
                    f"observation {observation_id!r} appears in multiple identity groups "
                    f"({assigned[observation_id]} and {group.garment_id})"
                )
            assigned[observation_id] = group.garment_id
            observation_to_garment[observation_id] = group.garment_id
            _, role = _parse_observation_id(observation_id)
            roles.add(role)
            garment_class = _observation_garment_class(final_root, observation_id)
            if garment_class:
                classes.add(garment_class)
            if observation_id != group.canonical_observation_id:
                alias_observations.add(observation_id)

        if len(roles) != 1:
            raise GarmentIdentityError(
                f"group {group.garment_id}: incompatible roles {sorted(roles)}"
            )
        if len(classes) > 1:
            raise GarmentIdentityError(
                f"group {group.garment_id}: incompatible garment classes {sorted(classes)}"
            )
        canonical_by_garment[group.garment_id] = group.canonical_observation_id

    for observation_id in observation_enrichments:
        if observation_id not in manifest_ids:
            raise GarmentIdentityError(
                f"unknown observation id {observation_id!r} in observation_enrichments"
            )
        if observation_id in assigned:
            raise GarmentIdentityError(
                f"observation enrichment {observation_id!r} "
                "cannot target an observation in an identity group"
            )

    default_garment_ids: dict[str, str] = {}
    for observation_id in sorted(manifest_ids):
        if observation_id in observation_to_garment:
            continue
        default_garment_ids[observation_id] = observation_id
        observation_to_garment[observation_id] = observation_id

    unique_garments = set(observation_to_garment.values())
    if len(unique_garments) != EXPECTED_UNIQUE_GARMENT_COUNT:
        raise GarmentIdentityError(
            f"expected {EXPECTED_UNIQUE_GARMENT_COUNT} unique garment ids, "
            f"got {len(unique_garments)}"
        )

    return ResolvedIdentityMap(
        groups=groups,
        observation_to_garment=observation_to_garment,
        canonical_by_garment=canonical_by_garment,
        alias_observations=frozenset(alias_observations),
        default_garment_ids=default_garment_ids,
        observation_enrichments=observation_enrichments,
    )


@dataclass(frozen=True)
class IdentityAliasTarget:
    garment_id: str
    canonical_observation_id: str


def lookup_identity_alias(
    observation_id: str,
    *,
    registry_path: Path,
) -> IdentityAliasTarget | None:
    """Return alias target when observation is a non-canonical member of an identity group."""
    payload = load_garment_identity_registry(registry_path)
    for group in parse_identity_groups(payload):
        if (
            observation_id in group.observation_ids
            and observation_id != group.canonical_observation_id
        ):
            return IdentityAliasTarget(
                garment_id=group.garment_id,
                canonical_observation_id=group.canonical_observation_id,
            )
    return None


def resolve_identity_map(
    *,
    repo_root: Path,
    final_root: Path = DEFAULT_FINAL_ROOT,
    registry_path: Path | None = None,
) -> ResolvedIdentityMap:
    resolved_registry = registry_path or default_registry_path(repo_root)
    payload = load_garment_identity_registry(resolved_registry)
    return validate_garment_identity_registry(
        payload=payload,
        final_root=final_root,
        repo_root=repo_root,
    )


def identity_label_for_observation(
    *,
    observation_id: str,
    identity_map: ResolvedIdentityMap,
) -> str | None:
    garment_id = identity_map.observation_to_garment.get(observation_id, observation_id)
    if garment_id == observation_id:
        return None
    canonical = next(
        (
            group.canonical_observation_id
            for group in identity_map.groups
            if group.garment_id == garment_id
        ),
        observation_id,
    )
    if observation_id == canonical:
        return f"canonical={garment_id}"
    return f"alias→{garment_id}"


def build_manifest_identity_block(
    *,
    identity_map: ResolvedIdentityMap,
    registry_path: Path,
    repo_root: Path,
    excluded_observations: frozenset[str] | None = None,
) -> dict[str, Any]:
    registry_text = registry_path.read_text(encoding="utf-8")
    excluded = excluded_observations or frozenset()
    indexed_observations = sorted(
        observation_id
        for observation_id, garment_id in identity_map.observation_to_garment.items()
        if observation_id not in identity_map.alias_observations and observation_id not in excluded
    )
    try:
        registry_rel = str(registry_path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        registry_rel = str(registry_path)

    return {
        "schema_version": 1,
        "registry_path": registry_rel.replace("\\", "/"),
        "registry_sha256": sha256_text(registry_text),
        "observation_count": EXPECTED_OBSERVATION_COUNT,
        "unique_garment_count": EXPECTED_UNIQUE_GARMENT_COUNT,
        "catalog_item_count": len(indexed_observations),
        "observation_to_garment": dict(sorted(identity_map.observation_to_garment.items())),
        "indexed_observations": indexed_observations,
        "groups": [
            {
                "garment_id": group.garment_id,
                "canonical_observation_id": group.canonical_observation_id,
                "observation_ids": list(group.observation_ids),
                "alias_observation_ids": list(group.alias_observation_ids),
                "reason": group.reason,
                "display_name": group.display_name,
                "facet_corrections": group.facet_corrections,
                "notes": group.notes,
                "canonical_selection_reason": group.canonical_selection_reason,
            }
            for group in identity_map.groups
        ],
        "observation_enrichments": [
            {
                "observation_id": enrichment.observation_id,
                "reason": enrichment.reason,
                "display_name": enrichment.display_name,
                "facet_corrections": enrichment.facet_corrections,
                "notes": enrichment.notes,
            }
            for enrichment in sorted(
                identity_map.observation_enrichments.values(),
                key=lambda row: row.observation_id,
            )
        ],
    }


def annotate_manifest_cases(
    *,
    manifest: dict[str, Any],
    identity_map: ResolvedIdentityMap,
) -> None:
    for case in manifest.get("cases", []):
        if not isinstance(case, dict):
            continue
        fixture = case.get("fixture")
        role = case.get("role")
        if not isinstance(fixture, str) or not isinstance(role, str):
            continue
        observation_id = catalog_id(fixture, role)
        garment_id = identity_map.observation_to_garment[observation_id]
        case["garment_id"] = garment_id
        if observation_id in identity_map.alias_observations:
            case["identity_role"] = "alias"
            case["catalog_indexed"] = False
        elif garment_id != observation_id:
            case["identity_role"] = "canonical"
            case["catalog_indexed"] = True
        else:
            case["identity_role"] = "default"
            case["catalog_indexed"] = True


def export_garment_identities(
    *,
    identity_map: ResolvedIdentityMap,
    manifest: dict[str, Any],
    registry_path: Path,
    repo_root: Path,
    final_root: Path,
    excluded_observations: frozenset[str] | None = None,
) -> dict[str, Any]:
    export = build_manifest_identity_block(
        identity_map=identity_map,
        registry_path=registry_path,
        repo_root=repo_root,
        excluded_observations=excluded_observations,
    )
    manifest_path = final_root / "manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    export["source_snapshot"] = {
        "manifest_schema_version": manifest.get("schema_version"),
        "manifest_packaged_at_utc": manifest.get("packaged_at_utc"),
        "manifest_sha256": sha256_text(manifest_text),
        "final_catalog_root": "final_catalog",
    }
    export["exported_at_utc"] = manifest.get("packaged_at_utc")
    return export


def write_garment_identities_export(
    *,
    payload: dict[str, Any],
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_registry(payload), encoding="utf-8")
    return output_path


def list_identity_groups(
    *,
    repo_root: Path,
    final_root: Path = DEFAULT_FINAL_ROOT,
    registry_path: Path | None = None,
) -> list[dict[str, Any]]:
    resolved = registry_path or default_registry_path(repo_root)
    payload = load_garment_identity_registry(resolved)
    identity_map = validate_garment_identity_registry(
        payload=payload,
        final_root=final_root,
        repo_root=repo_root,
    )
    rows: list[dict[str, Any]] = []
    for group in identity_map.groups:
        rows.append(
            {
                "garment_id": group.garment_id,
                "canonical_observation_id": group.canonical_observation_id,
                "alias_observation_ids": list(group.alias_observation_ids),
                "observation_ids": list(group.observation_ids),
                "display_name": group.display_name,
                "reason": group.reason,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory)",
    )
    common.add_argument(
        "--final-root",
        type=Path,
        default=DEFAULT_FINAL_ROOT,
        help="Final catalog directory relative to repo root",
    )
    common.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="Garment identity registry path relative to repo root",
    )
    common.add_argument(
        "--export",
        type=Path,
        default=DEFAULT_EXPORT_PATH,
        help="Export path for final_catalog/garment_identities.json",
    )

    parser = argparse.ArgumentParser(
        description="Validate and inspect user-confirmed garment identity registry."
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--final-root", type=Path, default=DEFAULT_FINAL_ROOT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT_PATH)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("validate", parents=[common], help="Validate registry")
    list_parser = subparsers.add_parser("list", parents=[common], help="List groups")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON")
    rebuild_parser = subparsers.add_parser(
        "rebuild",
        parents=[common],
        help="Validate registry and export final_catalog/garment_identities.json",
    )
    rebuild_parser.add_argument(
        "--annotate-manifest",
        action="store_true",
        help="Also annotate final_catalog/manifest.json case records in place",
    )

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    repo_root = args.repo_root.resolve()
    final_root = (repo_root / args.final_root).resolve()
    registry_path = args.registry if args.registry.is_absolute() else repo_root / args.registry
    export_path = args.export if args.export.is_absolute() else repo_root / args.export

    try:
        payload = load_garment_identity_registry(registry_path)
        identity_map = validate_garment_identity_registry(
            payload=payload,
            final_root=final_root,
            repo_root=repo_root,
        )

        if args.command == "validate":
            print(
                f"validated {registry_path} "
                f"(observations={EXPECTED_OBSERVATION_COUNT}, "
                f"unique_garments={EXPECTED_UNIQUE_GARMENT_COUNT}, "
                f"groups={len(identity_map.groups)})"
            )
            return 0

        if args.command == "list":
            rows = list_identity_groups(
                repo_root=repo_root,
                final_root=final_root,
                registry_path=registry_path,
            )
            if args.json:
                print(json.dumps(rows, indent=2, sort_keys=True))
            else:
                for row in rows:
                    aliases = ", ".join(row["alias_observation_ids"]) or "-"
                    print(
                        f"{row['garment_id']}: canonical={row['canonical_observation_id']} "
                        f"aliases=[{aliases}] display={row['display_name']!r}"
                    )
            return 0

        manifest_path = final_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        export_payload = export_garment_identities(
            identity_map=identity_map,
            manifest=manifest,
            registry_path=registry_path,
            repo_root=repo_root,
            final_root=final_root,
        )
        write_garment_identities_export(payload=export_payload, output_path=export_path)
        print(f"wrote {export_path}")

        if args.annotate_manifest:
            from cloth_store.catalog_exclusions import (
                annotate_manifest_exclusions,
                build_manifest_exclusion_block,
                default_exclusion_registry_path,
                resolve_exclusion_map,
            )

            annotate_manifest_cases(manifest=manifest, identity_map=identity_map)
            exclusion_map = resolve_exclusion_map(
                repo_root=repo_root,
                final_root=final_root,
                identity_registry_path=registry_path,
                registry_path=default_exclusion_registry_path(repo_root),
            )
            annotate_manifest_exclusions(
                manifest=manifest,
                exclusion_map=exclusion_map,
                identity_map=identity_map,
            )
            manifest["garment_identities"] = build_manifest_identity_block(
                identity_map=identity_map,
                registry_path=registry_path,
                repo_root=repo_root,
                excluded_observations=exclusion_map.excluded_observations,
            )
            manifest["catalog_exclusions"] = build_manifest_exclusion_block(
                exclusion_map=exclusion_map,
                registry_path=default_exclusion_registry_path(repo_root),
                repo_root=repo_root,
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"annotated {manifest_path}")
        return 0
    except GarmentIdentityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
