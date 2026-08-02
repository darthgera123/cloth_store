"""User-confirmed catalog exclusion registry for role-level observation suppression."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloth_store.catalog_garment_identities import (
    EXPECTED_OBSERVATION_COUNT,
    GarmentIdentityError,
    ResolvedIdentityMap,
    default_registry_path,
    load_garment_identity_registry,
    validate_garment_identity_registry,
)
from cloth_store.catalog_paths import catalog_id
from cloth_store.gemini_catalog_generate import sha256_text

DEFAULT_REGISTRY_PATH = Path("bench/catalog_generation/catalog_exclusions.json")
DEFAULT_FINAL_ROOT = Path("final_catalog")
DEFAULT_MANIFEST = DEFAULT_FINAL_ROOT / "manifest.json"

OBSERVATION_ID_PATTERN = re.compile(r"^outfit_\d+_(top|bottom|dress)$")
ALLOWED_REASONS = frozenset({"user_confirmed"})

EXPECTED_EXCLUDED_OBSERVATION_COUNT = 4
EXPECTED_CATALOG_ITEM_COUNT = 33


class CatalogExclusionError(ValueError):
    """Raised when catalog exclusion registry validation or resolution fails."""


@dataclass(frozen=True)
class ExcludedObservation:
    observation_id: str
    reason: str
    notes: str | None = None


@dataclass(frozen=True)
class ResolvedExclusionMap:
    excluded_observations: frozenset[str]
    entries: tuple[ExcludedObservation, ...]


def serialize_registry(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def default_exclusion_registry_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_REGISTRY_PATH


def load_exclusion_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CatalogExclusionError(f"missing catalog exclusion registry: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CatalogExclusionError("catalog exclusion registry must be a JSON object")
    return payload


def _parse_excluded_observation(raw: dict[str, Any]) -> ExcludedObservation:
    observation_id = raw.get("observation_id")
    reason = raw.get("reason")
    if not isinstance(observation_id, str) or not OBSERVATION_ID_PATTERN.fullmatch(observation_id):
        raise CatalogExclusionError(f"invalid excluded observation_id: {observation_id!r}")
    if reason not in ALLOWED_REASONS:
        raise CatalogExclusionError(
            f"excluded observation {observation_id!r} reason must be user_confirmed, got {reason!r}"
        )
    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise CatalogExclusionError(
            f"excluded observation {observation_id!r}: notes must be text when present"
        )
    return ExcludedObservation(
        observation_id=observation_id,
        reason=reason,
        notes=notes,
    )


def parse_excluded_observations(payload: dict[str, Any]) -> tuple[ExcludedObservation, ...]:
    if payload.get("schema_version") != 1:
        raise CatalogExclusionError("exclusion registry schema_version must be 1")
    excluded_raw = payload.get("excluded_observations")
    if not isinstance(excluded_raw, list) or not excluded_raw:
        raise CatalogExclusionError("excluded_observations must be a non-empty list")
    entries = [_parse_excluded_observation(raw) for raw in excluded_raw]
    observation_ids = [entry.observation_id for entry in entries]
    if len(set(observation_ids)) != len(observation_ids):
        raise CatalogExclusionError("duplicate observation_id in excluded_observations")
    return tuple(entries)


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


def _load_manifest_cases(final_root: Path) -> list[dict[str, Any]]:
    manifest_path = final_root / "manifest.json"
    if not manifest_path.is_file():
        raise CatalogExclusionError(f"missing final catalog manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])
    if not isinstance(cases, list):
        raise CatalogExclusionError("manifest cases must be a list")
    return cases


def validate_exclusion_registry(
    *,
    payload: dict[str, Any],
    final_root: Path,
    identity_map: ResolvedIdentityMap,
) -> ResolvedExclusionMap:
    entries = parse_excluded_observations(payload)
    excluded = frozenset(entry.observation_id for entry in entries)
    if len(excluded) != EXPECTED_EXCLUDED_OBSERVATION_COUNT:
        raise CatalogExclusionError(
            f"expected {EXPECTED_EXCLUDED_OBSERVATION_COUNT} excluded observations, "
            f"got {len(excluded)}"
        )

    manifest_ids = _manifest_observation_ids(_load_manifest_cases(final_root))
    if len(manifest_ids) != EXPECTED_OBSERVATION_COUNT:
        raise CatalogExclusionError(
            f"expected {EXPECTED_OBSERVATION_COUNT} manifest observations, got {len(manifest_ids)}"
        )

    for observation_id in excluded:
        if observation_id not in manifest_ids:
            raise CatalogExclusionError(
                f"unknown excluded observation id {observation_id!r} (not in manifest)"
            )
        if observation_id in identity_map.alias_observations:
            raise CatalogExclusionError(
                f"cannot exclude alias observation {observation_id!r}; "
                "exclude the indexed canonical observation instead"
            )
        for group in identity_map.groups:
            if (
                observation_id in group.observation_ids
                and observation_id == group.canonical_observation_id
            ):
                raise CatalogExclusionError(
                    f"cannot exclude canonical identity observation {observation_id!r}"
                )

    return ResolvedExclusionMap(excluded_observations=excluded, entries=entries)


def resolve_exclusion_map(
    *,
    repo_root: Path,
    final_root: Path = DEFAULT_FINAL_ROOT,
    registry_path: Path | None = None,
    identity_registry_path: Path | None = None,
) -> ResolvedExclusionMap:
    resolved_registry = registry_path or default_exclusion_registry_path(repo_root)
    payload = load_exclusion_registry(resolved_registry)
    identity_payload = load_garment_identity_registry(
        identity_registry_path or default_registry_path(repo_root)
    )
    identity_map = validate_garment_identity_registry(
        payload=identity_payload,
        final_root=final_root,
        repo_root=repo_root,
    )
    return validate_exclusion_registry(
        payload=payload,
        final_root=final_root,
        identity_map=identity_map,
    )


def annotate_manifest_exclusions(
    *,
    manifest: dict[str, Any],
    exclusion_map: ResolvedExclusionMap,
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
        if observation_id not in exclusion_map.excluded_observations:
            continue
        case["catalog_indexed"] = False
        case["identity_role"] = "excluded"
        case["garment_id"] = identity_map.observation_to_garment.get(observation_id, observation_id)


def build_manifest_exclusion_block(
    *,
    exclusion_map: ResolvedExclusionMap,
    registry_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    registry_text = registry_path.read_text(encoding="utf-8")
    try:
        registry_rel = str(registry_path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        registry_rel = str(registry_path)
    return {
        "schema_version": 1,
        "registry_path": registry_rel.replace("\\", "/"),
        "registry_sha256": sha256_text(registry_text),
        "excluded_observation_count": len(exclusion_map.excluded_observations),
        "excluded_observations": [
            {
                "observation_id": entry.observation_id,
                "reason": entry.reason,
                "notes": entry.notes,
            }
            for entry in exclusion_map.entries
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate catalog exclusion registry.")
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
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="Exclusion registry path relative to repo root",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    final_root = (repo_root / args.final_root).resolve()
    registry_path = args.registry if args.registry.is_absolute() else repo_root / args.registry

    try:
        exclusion_map = resolve_exclusion_map(
            repo_root=repo_root,
            final_root=final_root,
            registry_path=registry_path,
        )
        print(
            f"validated {registry_path} "
            f"(excluded={len(exclusion_map.excluded_observations)}, "
            f"catalog_items={EXPECTED_CATALOG_ITEM_COUNT})"
        )
        return 0
    except (CatalogExclusionError, GarmentIdentityError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
