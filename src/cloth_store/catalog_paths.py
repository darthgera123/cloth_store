"""Shared catalog asset path helpers for production pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CATALOG_MANIFEST = Path("bench/catalog_generation/manifest.json")
DEFAULT_PLAN1_MANIFEST = Path("bench/plan1_localization/manifest.json")
DEFAULT_CUTOUT_ROOT = Path("bench/plan1_localization/outputs/catalog_cutouts")
DEFAULT_MASK_ROOT = Path("bench/plan1_localization/outputs/masks")
DEFAULT_TEMPLATE_ROOT = Path("bench/catalog_templates/generated")
DEFAULT_SOURCE_PHOTO_DIR = Path("data")

CATALOG_ROLES: frozenset[str] = frozenset({"top", "bottom", "dress"})
CATALOG_ROLE_ORDER: tuple[str, ...] = ("top", "dress", "bottom")

# Backward-compatible catalog_id aliases (legacy id -> canonical indexed id).
CATALOG_ID_ALIASES: dict[str, str] = {
    "outfit_27_top": "outfit_27_dress",
}


def load_manifest(path: str | Path = DEFAULT_CATALOG_MANIFEST) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def catalog_id(fixture: str, role: str) -> str:
    return f"{fixture}_{role}"


def resolve_catalog_id(value: str) -> str:
    """Resolve a catalog_id or legacy alias to the canonical indexed catalog_id."""
    return CATALOG_ID_ALIASES.get(value, value)


def manifest_roles(manifest: dict[str, Any]) -> frozenset[str]:
    roles: set[str] = set()
    for case in manifest.get("cases", []):
        role = case.get("role")
        if isinstance(role, str):
            roles.add(role)
    return frozenset(roles)


def manifest_case_for(
    manifest: dict[str, Any],
    *,
    fixture: str,
    role: str,
) -> dict[str, Any] | None:
    for case in manifest.get("cases", []):
        if case.get("fixture") == fixture and case.get("role") == role:
            return case
    return None


def manifest_role_hint(
    manifest: dict[str, Any],
    *,
    fixture: str,
    role: str,
) -> str:
    """Human-readable hint when fixture/role is absent from the production manifest."""
    available = sorted(
        {
            str(case["role"])
            for case in manifest.get("cases", [])
            if case.get("fixture") == fixture and isinstance(case.get("role"), str)
        }
    )
    legacy = CATALOG_ID_ALIASES.get(catalog_id(fixture, role))
    parts = [f"no manifest case for {fixture}/{role}"]
    if available:
        parts.append(f"available roles: {', '.join(available)}")
    if legacy is not None:
        parts.append(f"legacy alias {catalog_id(fixture, role)!r} maps to {legacy!r}")
    return "; ".join(parts)


def load_plan1_manifest(path: str | Path = DEFAULT_PLAN1_MANIFEST) -> dict[str, Any]:
    return load_manifest(path)


def fixture_number(fixture_id: str) -> int:
    prefix = "outfit_"
    if not fixture_id.startswith(prefix):
        raise ValueError(f"unsupported fixture id: {fixture_id!r}")
    return int(fixture_id.removeprefix(prefix))


def fixture_id_from_number(number: int) -> str:
    if number < 1:
        raise ValueError(f"fixture number must be >= 1, got {number}")
    return f"outfit_{number}"


def fixture_range(*, from_number: int, to_number: int) -> list[str]:
    if from_number > to_number:
        raise ValueError(f"from_number ({from_number}) must be <= to_number ({to_number})")
    return [fixture_id_from_number(number) for number in range(from_number, to_number + 1)]


def resolve_plan1_fixtures(
    *,
    from_fixture: int | None = None,
    to_fixture: int | None = None,
    manifest: dict[str, Any] | None = None,
    manifest_path: str | Path = DEFAULT_PLAN1_MANIFEST,
) -> list[str]:
    """Resolve fixture ids from an inclusive numeric range or the full plan1 manifest."""
    if from_fixture is not None or to_fixture is not None:
        if from_fixture is None or to_fixture is None:
            raise ValueError("both from_fixture and to_fixture are required for range selection")
        return fixture_range(from_number=from_fixture, to_number=to_fixture)

    return plan1_fixture_ids(manifest=manifest, manifest_path=manifest_path)


def plan1_fixture_ids(
    manifest: dict[str, Any] | None = None,
    *,
    manifest_path: str | Path = DEFAULT_PLAN1_MANIFEST,
) -> list[str]:
    payload = manifest if manifest is not None else load_plan1_manifest(manifest_path)
    return [fixture["id"] for fixture in payload["fixtures"]]


def plan1_fixture_entry(
    fixture_id: str,
    *,
    manifest: dict[str, Any] | None = None,
    manifest_path: str | Path = DEFAULT_PLAN1_MANIFEST,
) -> dict[str, Any]:
    payload = manifest if manifest is not None else load_plan1_manifest(manifest_path)
    for fixture in payload["fixtures"]:
        if fixture["id"] == fixture_id:
            return fixture
    raise KeyError(f"fixture not found in plan1 manifest: {fixture_id}")


def resolve_fixture_source_path(
    fixture_id: str,
    *,
    repo_root: str | Path,
    manifest: dict[str, Any] | None = None,
    manifest_path: str | Path = DEFAULT_PLAN1_MANIFEST,
) -> Path:
    """Resolve a fixture source photo under repo root without ad-hoc root copies."""
    root = Path(repo_root).expanduser().resolve()
    entry = plan1_fixture_entry(fixture_id, manifest=manifest, manifest_path=manifest_path)
    manifest_file = Path(manifest_path)
    if not manifest_file.is_absolute():
        manifest_file = root / manifest_file

    candidates: list[Path] = []
    image_ref = entry.get("image")
    if image_ref:
        candidates.append((manifest_file.parent / image_ref).resolve())
    candidates.append(root / DEFAULT_SOURCE_PHOTO_DIR / f"{fixture_id}.jpeg")
    candidates.append(root / f"{fixture_id}.jpeg")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"source photo not found for {fixture_id}; searched: {searched}")


def catalog_cutout_path(
    *,
    cutout_root: str | Path,
    fixture_id: str,
    role: str,
) -> Path:
    return Path(cutout_root) / fixture_id / f"catalog_{role}.png"


def template_png_path(
    *,
    template_root: str | Path = DEFAULT_TEMPLATE_ROOT,
    template_id: str,
) -> Path:
    return Path(template_root) / f"{template_id}.png"


def sam_mask_path(
    *,
    mask_root: str | Path,
    fixture_id: str,
    role: str,
) -> Path:
    return Path(mask_root) / fixture_id / f"{role}.png"


def iter_cases(
    manifest: dict[str, Any],
    *,
    fixture_ids: list[str] | None = None,
    roles: list[str] | None = None,
) -> list[dict[str, str]]:
    allowed_fixtures = set(fixture_ids) if fixture_ids else None
    allowed_roles = set(roles) if roles else None

    cases: list[dict[str, str]] = []
    for case in manifest["cases"]:
        fixture = case["fixture"]
        role = case["role"]
        if allowed_fixtures is not None and fixture not in allowed_fixtures:
            continue
        if allowed_roles is not None and role not in allowed_roles:
            continue
        cases.append({"fixture": fixture, "role": role})
    return cases
