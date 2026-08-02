"""Preflight validation and manifest sync for catalog production batches."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloth_store.catalog_paths import (
    DEFAULT_CATALOG_MANIFEST,
    catalog_cutout_path,
    load_manifest,
    resolve_fixture_source_path,
    resolve_plan1_fixtures,
)
from cloth_store.catalog_pipeline import (
    build_pipeline_plan,
    select_template_for_pipeline,
)
from cloth_store.catalog_template_selector import (
    DEFAULT_GARMENT_ATTRIBUTES,
    garment_attributes_for_case,
    load_garment_attributes,
    validate_all_manifest_cases,
)
from cloth_store.catalog_vlm_records import load_extraction_record


def load_localization_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class PreflightCase:
    fixture: str
    role: str
    layout: str
    garment_class: str
    sleeve_length: str | None
    skirt_style: str | None
    template_id: str
    confidence: str
    reason: str
    review_required: bool
    cutout_ok: bool
    vlm_ok: bool
    source_ok: bool

    def garment_attributes_record(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "role": self.role,
            "garment_class": self.garment_class,
            "sleeve_length": self.sleeve_length,
            "skirt_style": self.skirt_style,
            "source_evidence": self.reason,
        }

    def manifest_case(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "role": self.role,
            "template_id": self.template_id,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _roles_for_fixture(
    *,
    fixture_id: str,
    repo_root: Path,
    json_dir: Path,
) -> tuple[str, list[str]]:
    json_path = json_dir / f"{fixture_id}.json"
    if not json_path.is_file():
        raise FileNotFoundError(f"bbox JSON missing for {fixture_id}: {json_path}")
    localization = load_localization_json(json_path)
    layout = str(localization["layout"])
    if layout == "dress":
        return layout, ["dress"]
    if layout == "separates":
        roles = [role for role in ("top", "bottom") if role in localization]
        return layout, roles
    raise ValueError(f"unsupported layout for {fixture_id}: {layout!r}")


def build_preflight_case(
    *,
    repo_root: Path,
    fixture_id: str,
    role: str,
    layout: str,
    vlm_root: Path,
    cutout_root: Path,
) -> PreflightCase:
    source_ok = False
    try:
        source = resolve_fixture_source_path(fixture_id, repo_root=repo_root)
        source_ok = source.is_file()
    except FileNotFoundError:
        source_ok = False

    cutout = repo_root / catalog_cutout_path(
        cutout_root=cutout_root,
        fixture_id=fixture_id,
        role=role,
    )
    cutout_ok = cutout.is_file()

    vlm_path = vlm_root / f"{fixture_id}_{role}.attributes.json"
    vlm_ok = vlm_path.is_file()
    vlm_attributes: dict[str, dict[str, str]] | None = None
    if vlm_ok:
        vlm_attributes = load_extraction_record(vlm_path)["attributes"]

    selection = select_template_for_pipeline(
        repo_root=repo_root,
        fixture_id=fixture_id,
        role=role,
        vlm_attributes=vlm_attributes,
        user_override=None,
        attributes_path=repo_root / DEFAULT_GARMENT_ATTRIBUTES,
    )
    reviewed = load_garment_attributes(repo_root / DEFAULT_GARMENT_ATTRIBUTES)
    reviewed_record = garment_attributes_for_case(reviewed, fixture=fixture_id, role=role)
    garment_class = (
        reviewed_record.garment_class
        if reviewed_record is not None
        else (vlm_attributes or {}).get("garment_class", {}).get("value", "unknown")
    )
    sleeve_length = reviewed_record.sleeve_length if reviewed_record else None
    skirt_style = reviewed_record.skirt_style if reviewed_record else None
    review_required = selection.confidence == "low"
    if layout == "dress":
        review_required = True

    return PreflightCase(
        fixture=fixture_id,
        role=role,
        layout=layout,
        garment_class=garment_class,
        sleeve_length=sleeve_length,
        skirt_style=skirt_style,
        template_id=selection.template_id,
        confidence=selection.confidence,
        reason=selection.reason,
        review_required=review_required,
        cutout_ok=cutout_ok,
        vlm_ok=vlm_ok,
        source_ok=source_ok,
    )


def run_preflight(
    *,
    repo_root: Path,
    fixture_ids: list[str],
    json_dir: Path | None = None,
    vlm_root: Path | None = None,
    cutout_root: Path | None = None,
) -> list[PreflightCase]:
    root = repo_root.resolve()
    resolved_json = json_dir or root / "bench/plan1_localization/outputs"
    resolved_vlm = vlm_root or root / "bench/catalog_generation/vlm_attributes"
    resolved_cutouts = cutout_root or root / "bench/plan1_localization/outputs/catalog_cutouts"

    cases: list[PreflightCase] = []
    for fixture_id in fixture_ids:
        layout, roles = _roles_for_fixture(
            fixture_id=fixture_id,
            repo_root=root,
            json_dir=resolved_json,
        )
        for role in roles:
            cases.append(
                build_preflight_case(
                    repo_root=root,
                    fixture_id=fixture_id,
                    role=role,
                    layout=layout,
                    vlm_root=resolved_vlm,
                    cutout_root=resolved_cutouts,
                )
            )
    return cases


def sync_manifest_records(
    *,
    repo_root: Path,
    cases: list[PreflightCase],
    garment_attributes_path: Path,
    catalog_manifest_path: Path,
    only_supported: bool = True,
) -> tuple[int, int]:
    """Append or update garment_attributes and catalog_generation manifest cases."""
    ga_path = garment_attributes_path
    ga_payload = json.loads(ga_path.read_text(encoding="utf-8"))
    ga_by_key = {(record["fixture"], record["role"]): record for record in ga_payload["cases"]}

    cm_path = catalog_manifest_path
    cm_payload = json.loads(cm_path.read_text(encoding="utf-8"))
    cm_by_key = {(case["fixture"], case["role"]): case for case in cm_payload["cases"]}

    ga_added = 0
    cm_added = 0
    for case in cases:
        if only_supported and case.review_required:
            continue
        key = (case.fixture, case.role)
        ga_record = case.garment_attributes_record()
        if key not in ga_by_key:
            ga_payload["cases"].append(ga_record)
            ga_by_key[key] = ga_record
            ga_added += 1
        else:
            ga_by_key[key].update(ga_record)

        cm_case = case.manifest_case()
        if key not in cm_by_key:
            cm_payload["cases"].append(cm_case)
            cm_by_key[key] = cm_case
            cm_added += 1
        else:
            cm_by_key[key].update(cm_case)

    ga_path.write_text(json.dumps(ga_payload, indent=2) + "\n", encoding="utf-8")
    cm_path.write_text(json.dumps(cm_payload, indent=2) + "\n", encoding="utf-8")
    return ga_added, cm_added


def validate_pipeline_readiness(
    *,
    repo_root: Path,
    cases: list[PreflightCase],
) -> list[str]:
    errors: list[str] = []
    for case in cases:
        label = f"{case.fixture}/{case.role}"
        if not case.source_ok:
            errors.append(f"{label}: missing source photo")
        if not case.cutout_ok:
            errors.append(f"{label}: missing cutout")
        if not case.vlm_ok:
            errors.append(f"{label}: missing VLM attributes")
        if case.review_required:
            errors.append(f"{label}: review_required ({case.reason})")
            continue
        try:
            build_pipeline_plan(
                repo_root=repo_root,
                fixture_id=case.fixture,
                role=case.role,
            )
        except Exception as exc:  # noqa: BLE001 - aggregate preflight blockers
            errors.append(f"{label}: pipeline plan failed: {exc}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preflight catalog batch cases before Gemini billing."
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--from-fixture", type=int)
    parser.add_argument("--to-fixture", type=int)
    parser.add_argument(
        "--sync", action="store_true", help="Update garment_attributes + catalog manifest."
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    if args.from_fixture is None or args.to_fixture is None:
        print("error: --from-fixture and --to-fixture are required", file=sys.stderr)
        raise SystemExit(1)

    fixture_ids = resolve_plan1_fixtures(
        from_fixture=args.from_fixture,
        to_fixture=args.to_fixture,
    )
    cases = run_preflight(repo_root=repo_root, fixture_ids=fixture_ids)

    print(f"Preflight {args.from_fixture}-{args.to_fixture}: {len(cases)} case(s)")
    for case in cases:
        flags = []
        if case.review_required:
            flags.append("REVIEW")
        if not case.cutout_ok:
            flags.append("NO_CUTOUT")
        if not case.vlm_ok:
            flags.append("NO_VLM")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        print(
            f"  {case.fixture}/{case.role}: layout={case.layout} "
            f"class={case.garment_class} template={case.template_id} "
            f"({case.confidence}){suffix}"
        )

    if args.sync:
        ga_path = repo_root / DEFAULT_GARMENT_ATTRIBUTES
        cm_path = repo_root / DEFAULT_CATALOG_MANIFEST
        ga_added, cm_added = sync_manifest_records(
            repo_root=repo_root,
            cases=cases,
            garment_attributes_path=ga_path,
            catalog_manifest_path=cm_path,
        )
        print(f"Synced garment_attributes (+{ga_added}) and catalog manifest (+{cm_added})")

    errors = validate_pipeline_readiness(repo_root=repo_root, cases=cases)
    if args.sync:
        cm_payload = load_manifest(repo_root / DEFAULT_CATALOG_MANIFEST)
        discrepancies = validate_all_manifest_cases(
            cm_payload,
            attributes_path=repo_root / DEFAULT_GARMENT_ATTRIBUTES,
        )
        for item in discrepancies:
            errors.append(f"{item['fixture']}/{item['role']}: manifest mismatch: {item}")

    if errors:
        print("\nBlockers:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        if not args.validate_only:
            raise SystemExit(1)

    print("ok: preflight passed")


if __name__ == "__main__":
    main()
