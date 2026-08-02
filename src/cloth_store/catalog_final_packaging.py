"""Self-contained final catalog packaging for human review and downstream use."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from cloth_store.catalog_garment_identities import (
    annotate_manifest_cases,
    build_manifest_identity_block,
    default_registry_path,
    identity_label_for_observation,
    load_garment_identity_registry,
    validate_garment_identity_registry,
)
from cloth_store.catalog_output_contract import CANONICAL_COST_1K_USD
from cloth_store.catalog_paths import (
    CATALOG_ROLE_ORDER,
    DEFAULT_CATALOG_MANIFEST,
    catalog_id,
    iter_cases,
    load_manifest,
)
from cloth_store.catalog_pipeline import PRODUCTION_NAMESPACE, production_case_dir
from cloth_store.catalog_templates import WHITE_BACKGROUND
from cloth_store.catalog_vlm_records import load_extraction_record
from cloth_store.gemini_catalog_generate import sha256_file, sha256_text
from cloth_store.gemini_catalog_request import load_request_artifact

DEFAULT_FINAL_ROOT = Path("final_catalog")
DEFAULT_MANIFEST = DEFAULT_CATALOG_MANIFEST
DEFAULT_OUTPUT_ROOT = Path("bench/catalog_generation/outputs")
DEFAULT_VLM_ROOT = Path("bench/catalog_generation/vlm_attributes")
DEFAULT_OVERRIDE_ROOT = Path("bench/catalog_generation/overrides")

ROLE_INPUT_NAMES = {
    "garment_identity": "input_segmented.png",
    "template_geometry": "input_template.png",
    "derived_geometry": "input_template.png",
    "garment_detail": "input_detail.png",
}


@dataclass(frozen=True)
class FinalCaseStatus:
    fixture: str
    role: str
    status: str
    error: str | None = None


class FinalCatalogPackagingError(RuntimeError):
    """Raised when final catalog packaging cannot proceed safely."""


def packaging_override_path(repo_root: Path, fixture: str, role: str) -> Path:
    return repo_root / DEFAULT_OVERRIDE_ROOT / f"{fixture}_{role}.override.json"


def _copy_bytes(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise FinalCatalogPackagingError(f"missing source file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return sha256_file(destination)


def _load_panel_image(path: Path, *, size: int) -> Image.Image:
    with Image.open(path) as image:
        panel = image.convert("RGB")
        panel.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size, size), WHITE_BACKGROUND)
        offset = ((size - panel.width) // 2, (size - panel.height) // 2)
        canvas.paste(panel, offset)
        return canvas


def _outfit_number(fixture: str) -> int:
    if not fixture.startswith("outfit_"):
        raise FinalCatalogPackagingError(f"unsupported fixture id: {fixture!r}")
    return int(fixture.split("_", 1)[1])


def _group_outfits_for_contact_sheets(
    cases: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group case records by outfit with top before bottom, sorted by outfit number."""
    by_outfit: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_outfit.setdefault(case["fixture"], []).append(case)

    role_order = {role: index for index, role in enumerate(CATALOG_ROLE_ORDER)}
    outfits: list[tuple[str, list[dict[str, Any]]]] = []
    for fixture in sorted(by_outfit.keys(), key=_outfit_number):
        roles = sorted(by_outfit[fixture], key=lambda item: role_order.get(item["role"], 99))
        outfits.append((fixture, roles))
    return outfits


def _contact_sheet_batch_filename(start: int, end: int) -> str:
    return f"outfits_{start:02d}-{end:02d}.jpg"


def _render_contact_sheet_image(
    *,
    cases: list[dict[str, Any]],
    final_root: Path,
    output_path: Path,
    identity_labels: dict[str, str] | None = None,
    thumb: int = 128,
) -> None:
    cols = ["Segmented", "Template", "Output 512"]
    header_h = 24
    label_h = 22
    margin = 6
    row_header_w = 118
    top_labels_h = 22
    cell_w = thumb + 2 * margin
    rows = len(cases)
    sheet_w = row_header_w + len(cols) * cell_w + margin
    sheet_h = top_labels_h + rows * (thumb + header_h + label_h + margin) + margin
    sheet = Image.new("RGB", (sheet_w, sheet_h), WHITE_BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for col_index, label in enumerate(cols):
        x = row_header_w + col_index * cell_w + margin
        draw.text((x, 4), label, fill=(20, 20, 20), font=font)

    for row_index, case in enumerate(cases):
        fixture = case["fixture"]
        role = case["role"]
        y = top_labels_h + row_index * (thumb + header_h + label_h + margin)
        status_suffix = ""
        if case.get("status") not in (None, "ok"):
            status_suffix = f"\n[{case.get('status', 'missing')}]"
        elif case.get("review_required"):
            status_suffix = "\n[review_required]"
        identity_suffix = ""
        if identity_labels:
            observation_id = catalog_id(fixture, role)
            label = identity_labels.get(observation_id)
            if label:
                identity_suffix = f"\n[{label}]"
        row_label = (
            f"{fixture}/{role}\n{case.get('template_id', '?')}{status_suffix}{identity_suffix}"
        )
        if role == "dress" or str(case.get("template_id", "")).startswith("dress_"):
            row_label = row_label.replace(f"{fixture}/{role}", f"{fixture}/{role} [one-piece]")
        draw.text((margin, y + 6), row_label, fill=(20, 20, 20), font=font)
        case_dir = final_root / fixture / role
        panels = [
            case_dir / "input_segmented.png",
            case_dir / "input_template.png",
            case_dir / "output.png",
        ]
        for col_index, panel_path in enumerate(panels):
            x = row_header_w + col_index * cell_w + margin
            if panel_path.is_file():
                sheet.paste(_load_panel_image(panel_path, size=thumb), (x, y + header_h))
            else:
                draw.rectangle(
                    [x, y + header_h, x + thumb, y + header_h + thumb],
                    outline=(180, 180, 180),
                )
                status = case.get("status", "missing")
                draw.text((x + 8, y + header_h + 8), status, fill=(120, 120, 120), font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def build_batched_contact_sheets(
    *,
    final_root: Path,
    cases: list[dict[str, Any]],
    identity_labels: dict[str, str] | None = None,
    batch_size_outfits: int = 4,
    thumb: int = 128,
) -> dict[str, Any]:
    """Build deterministic outfit-batched contact sheets under final_root/contact_sheets/."""
    if batch_size_outfits < 1:
        raise FinalCatalogPackagingError("contact_sheet_batch_size must be >= 1")

    outfit_groups = _group_outfits_for_contact_sheets(cases)
    sheets_dir = final_root / "contact_sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)

    sheet_records: list[dict[str, Any]] = []
    for batch_start in range(0, len(outfit_groups), batch_size_outfits):
        batch = outfit_groups[batch_start : batch_start + batch_size_outfits]
        batch_fixtures = [fixture for fixture, _ in batch]
        start_num = _outfit_number(batch_fixtures[0])
        end_num = _outfit_number(batch_fixtures[-1])
        batch_cases: list[dict[str, Any]] = []
        for _, roles in batch:
            batch_cases.extend(roles)

        filename = _contact_sheet_batch_filename(start_num, end_num)
        output_path = sheets_dir / filename
        _render_contact_sheet_image(
            cases=batch_cases,
            final_root=final_root,
            output_path=output_path,
            identity_labels=identity_labels,
            thumb=thumb,
        )
        sheet_records.append(
            {
                "path": f"final_catalog/contact_sheets/{filename}",
                "filename": filename,
                "outfit_range": {"start": start_num, "end": end_num},
                "outfits": batch_fixtures,
                "case_count": len(batch_cases),
                "sha256": sha256_file(output_path),
            }
        )

    legacy_monolith = final_root / "contact_sheet.jpg"
    if legacy_monolith.is_file():
        legacy_monolith.unlink()

    covered_outfits = [outfit for sheet in sheet_records for outfit in sheet["outfits"]]
    expected_outfits = [fixture for fixture, _ in outfit_groups]
    if covered_outfits != expected_outfits:
        raise FinalCatalogPackagingError(
            "contact sheet batch coverage mismatch: "
            f"expected {expected_outfits}, got {covered_outfits}"
        )

    return {
        "batch_size_outfits": batch_size_outfits,
        "directory": "final_catalog/contact_sheets",
        "sheets": sheet_records,
    }


def _case_metadata_from_production(
    *,
    repo_root: Path,
    fixture: str,
    role: str,
    production_metadata: dict[str, Any],
    artifact: dict[str, Any],
    vlm_path: Path | None,
    override_path: Path | None,
    packaged_inputs: list[dict[str, Any]],
    generated_or_reused: str,
) -> dict[str, Any]:
    return {
        "fixture": fixture,
        "role": role,
        "status": "ok",
        "generated_or_reused": generated_or_reused,
        "template_id": production_metadata.get("template_id"),
        "template_selection": production_metadata.get("template_selection"),
        "review_required": (
            production_metadata.get("template_selection", {}).get("confidence") == "low"
        ),
        "user_override_applied": production_metadata.get("user_override") is not None,
        "source_paths": {
            "production_metadata": repo_relative(
                repo_root, production_metadata_path(repo_root, fixture, role)
            ),
            "artifact": production_metadata.get("artifact_path"),
            "vlm_attributes": repo_relative(repo_root, vlm_path) if vlm_path else None,
            "override": (
                repo_relative(repo_root, override_path)
                if override_path and override_path.is_file()
                else None
            ),
        },
        "packaged_inputs": packaged_inputs,
        "outputs": {
            "output_1k": {
                "path": f"{fixture}/{role}/output_1k.png",
                "sha256": production_metadata.get("outputs", {}).get("raw", {}).get("sha256"),
            },
            "output_512": {
                "path": f"{fixture}/{role}/output.png",
                "sha256": production_metadata.get("outputs", {}).get("catalog", {}).get("sha256"),
            },
        },
        "prompt_policy_version": production_metadata.get("prompt_policy_version"),
        "prompt_sha256": production_metadata.get("prompt_sha256"),
        "model_id": production_metadata.get("model_id"),
        "request_settings": production_metadata.get("request_settings"),
        "texture_qc": production_metadata.get("texture_qc"),
        "generation_calls": production_metadata.get("generation_calls"),
        "estimated_cost_usd": production_metadata.get("estimated_cost_usd"),
        "reuse_source": production_metadata.get("reuse_source"),
        "promoted_from_reference": production_metadata.get("production_policy", {}).get(
            "promoted_from_reference"
        ),
        "promoted_from_candidate": production_metadata.get("production_policy", {}).get(
            "promoted_from_candidate"
        ),
        "candidate_request_sha256": production_metadata.get("production_policy", {}).get(
            "candidate_request_sha256"
        ),
        "derived_geometry_sha256": production_metadata.get("production_policy", {}).get(
            "derived_geometry_sha256"
        ),
        "artifact_image_roles": [
            {"order": record["order"], "role": record["role"], "sha256": record["sha256"]}
            for record in artifact.get("images", [])
        ],
        "vlm_attribute_json_sha256": production_metadata.get("user_override", {}).get(
            "vlm_attribute_json_sha256"
        )
        or (
            sha256_text(json.dumps(load_extraction_record(vlm_path), sort_keys=True))
            if vlm_path and vlm_path.is_file()
            else None
        ),
    }


def production_metadata_path(repo_root: Path, fixture: str, role: str) -> Path:
    case_dir = production_case_dir(
        output_root=repo_root / DEFAULT_OUTPUT_ROOT,
        fixture_id=fixture,
    )
    return case_dir / f"{role}.run.json"


def repo_relative(repo_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def default_vlm_path(repo_root: Path, fixture: str, role: str) -> Path:
    return repo_root / DEFAULT_VLM_ROOT / f"{fixture}_{role}.attributes.json"


def package_case(
    *,
    repo_root: Path,
    fixture: str,
    role: str,
    final_root: Path,
) -> dict[str, Any]:
    metadata_path = production_metadata_path(repo_root, fixture, role)
    if not metadata_path.is_file():
        return {
            "fixture": fixture,
            "role": role,
            "status": "missing",
            "error": f"production output missing: {repo_relative(repo_root, metadata_path)}",
        }

    production_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    artifact_rel = production_metadata.get("artifact_path")
    if not artifact_rel:
        raise FinalCatalogPackagingError(f"artifact_path missing in {metadata_path}")
    artifact = load_request_artifact(repo_root / artifact_rel)

    case_dir = final_root / fixture / role
    case_dir.mkdir(parents=True, exist_ok=True)

    packaged_inputs: list[dict[str, Any]] = []
    for record in sorted(artifact["images"], key=lambda item: item["order"]):
        role_name = record["role"]
        dest_name = ROLE_INPUT_NAMES.get(role_name)
        if dest_name is None:
            continue
        source = repo_root / record["path"]
        dest = case_dir / dest_name
        digest = _copy_bytes(source, dest)
        if digest != record["sha256"]:
            raise FinalCatalogPackagingError(
                f"hash mismatch for {fixture}/{role} {dest_name}: "
                f"expected {record['sha256']}, got {digest}"
            )
        packaged_inputs.append(
            {
                "filename": dest_name,
                "role": role_name,
                "order": record["order"],
                "source_path": record["path"],
                "sha256": digest,
            }
        )

    raw_src = repo_root / production_metadata["outputs"]["raw"]["path"]
    catalog_src = repo_root / production_metadata["outputs"]["catalog"]["path"]
    raw_digest = _copy_bytes(raw_src, case_dir / "output_1k.png")
    catalog_digest = _copy_bytes(catalog_src, case_dir / "output.png")
    if raw_digest != production_metadata["outputs"]["raw"]["sha256"]:
        raise FinalCatalogPackagingError(f"raw output hash mismatch for {fixture}/{role}")
    if catalog_digest != production_metadata["outputs"]["catalog"]["sha256"]:
        raise FinalCatalogPackagingError(f"512 output hash mismatch for {fixture}/{role}")

    vlm_path = default_vlm_path(repo_root, fixture, role)
    if vlm_path.is_file():
        attr_dest = case_dir / "attributes.json"
        attr_digest = _copy_bytes(vlm_path, attr_dest)
        packaged_inputs.append(
            {
                "filename": "attributes.json",
                "role": "vlm_attributes",
                "source_path": repo_relative(repo_root, vlm_path),
                "sha256": attr_digest,
            }
        )

    override_path = packaging_override_path(repo_root, fixture, role)
    generated_or_reused = (
        "generated" if production_metadata.get("generation_calls", 0) > 0 else "reused"
    )
    case_metadata = _case_metadata_from_production(
        repo_root=repo_root,
        fixture=fixture,
        role=role,
        production_metadata=production_metadata,
        artifact=artifact,
        vlm_path=vlm_path if vlm_path.is_file() else None,
        override_path=override_path,
        packaged_inputs=packaged_inputs,
        generated_or_reused=generated_or_reused,
    )
    metadata_dest = case_dir / "metadata.json"
    metadata_dest.write_text(
        json.dumps(case_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return case_metadata


def build_readme(*, final_root: Path, manifest: dict[str, Any]) -> Path:
    contact_sheets = manifest.get("contact_sheets", {})
    sheet_lines = "\n".join(
        f"    - `{sheet['path']}` (outfits {sheet['outfit_range']['start']}–"
        f"{sheet['outfit_range']['end']})"
        for sheet in contact_sheets.get("sheets", [])
    )
    readme = f"""# Final catalog ({PRODUCTION_NAMESPACE})

Self-contained packaging of production catalog inputs and outputs for all 12 outfits
(outfit_1…outfit_12 × top/bottom). Each case directory contains exact byte copies of
model-bound inputs, structured VLM attributes when available, native 1K output, and
the canonical 512 derivative.

## Layout

```
final_catalog/
  README.md
  manifest.json
  catalog.json
  contact_sheets/
    outfits_01-04.jpg
    outfits_05-08.jpg
    outfits_09-12.jpg
  outfit_N/
    top|bottom/
      input_segmented.png
      input_template.png
      input_detail.png    # tops only, when sent to Gemini
      attributes.json     # when VLM extraction exists
      output_1k.png
      output.png
      metadata.json
```

## Contact sheets

Batched review grids ({contact_sheets.get("batch_size_outfits", 4)} outfits per sheet;
top and bottom kept together per outfit):

{sheet_lines or "  (none)"}

## Contract

- **Authoritative source:** segmented cutout (color, material, texture, details).
- **Template:** geometry/silhouette only; never transfers template gray or fabric.
- **Generation:** one native 1K Gemini call per case (`gemini-3.1-flash-image`), then
  deterministic local 512 LANCZOS derivative.
- **Reuse:** exact-hash reuse or reference promotion when artifacts match; no hidden retries.

## Regeneration CLI

Dry-run (validate, zero API calls):

```bash
uv run cloth-store-catalog-pipeline --fixture outfit_1 --role top --dry-run
```

Generate or reuse production outputs:

```bash
uv run cloth-store-catalog-pipeline --fixture outfit_1 --role top
uv run cloth-store-catalog-pipeline --fixture outfit_1 --role top --regenerate  # billable
```

Repackage after production changes:

```bash
uv run cloth-store-catalog-final-packaging --repo-root .
uv run cloth-store-catalog-final-packaging --repo-root . --contact-sheet-batch-size 4
```

## Summary

- Packaged at: `{manifest["packaged_at_utc"]}`
- Cases ok: {manifest["summary"]["ok"]} / {manifest["summary"]["total"]}
- Cases missing/error: {manifest["summary"]["missing_or_error"]}
- Estimated output cost (new generations): ${CANONICAL_COST_1K_USD:.3f} per 1K call
"""
    path = final_root / "README.md"
    path.write_text(readme, encoding="utf-8")
    return path


def package_final_catalog(
    *,
    repo_root: Path,
    final_root: Path | None = None,
    manifest_path: Path | None = None,
    contact_sheet_batch_size: int = 4,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    resolved_final = (final_root or repo_root / DEFAULT_FINAL_ROOT).resolve()
    if resolved_final.exists():
        shutil.rmtree(resolved_final)
    resolved_final.mkdir(parents=True, exist_ok=True)

    bench_manifest = manifest_path or repo_root / DEFAULT_MANIFEST
    cases = iter_cases(load_manifest(bench_manifest))
    packaged_cases: list[dict[str, Any]] = []
    for case in cases:
        try:
            packaged = package_case(
                repo_root=repo_root,
                fixture=case["fixture"],
                role=case["role"],
                final_root=resolved_final,
            )
        except FinalCatalogPackagingError as exc:
            packaged = {
                "fixture": case["fixture"],
                "role": case["role"],
                "status": "error",
                "error": str(exc),
            }
        packaged_cases.append(packaged)

    ok_cases = [case for case in packaged_cases if case.get("status") == "ok"]
    for case in ok_cases:
        case["template_id"] = case.get("template_id")

    registry_path = default_registry_path(repo_root)
    identity_labels: dict[str, str] | None = None
    identity_map = None
    if registry_path.is_file():
        registry_payload = load_garment_identity_registry(registry_path)
        identity_map = validate_garment_identity_registry(
            payload=registry_payload,
            final_root=resolved_final,
            repo_root=repo_root,
            cases=packaged_cases,
        )
        annotate_manifest_cases(manifest={"cases": packaged_cases}, identity_map=identity_map)
        identity_labels = {}
        for case in packaged_cases:
            fixture = case.get("fixture")
            role = case.get("role")
            if not isinstance(fixture, str) or not isinstance(role, str):
                continue
            observation_id = catalog_id(fixture, role)
            label = identity_label_for_observation(
                observation_id=observation_id,
                identity_map=identity_map,
            )
            if label:
                identity_labels[observation_id] = label

    contact_sheets = build_batched_contact_sheets(
        final_root=resolved_final,
        cases=packaged_cases,
        identity_labels=identity_labels,
        batch_size_outfits=contact_sheet_batch_size,
    )

    manifest = {
        "schema_version": 1,
        "namespace": PRODUCTION_NAMESPACE,
        "packaged_at_utc": datetime.now(tz=UTC).isoformat(),
        "repo_root": str(repo_root),
        "summary": {
            "total": len(packaged_cases),
            "ok": len(ok_cases),
            "missing_or_error": len(packaged_cases) - len(ok_cases),
        },
        "cases": packaged_cases,
        "contact_sheets": contact_sheets,
    }
    if identity_map is not None:
        manifest["garment_identities"] = build_manifest_identity_block(
            identity_map=identity_map,
            registry_path=registry_path,
            repo_root=repo_root,
        )
    manifest_path_out = resolved_final / "manifest.json"
    manifest_path_out.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    build_readme(final_root=resolved_final, manifest=manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Package final catalog for human review.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--final-root", type=Path, default=DEFAULT_FINAL_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--contact-sheet-batch-size",
        type=int,
        default=4,
        help="Number of outfits per contact sheet batch (default: 4).",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = repo_root / manifest_path
    final_root = args.final_root
    if not final_root.is_absolute():
        final_root = repo_root / final_root

    try:
        manifest = package_final_catalog(
            repo_root=repo_root,
            final_root=final_root,
            manifest_path=manifest_path,
            contact_sheet_batch_size=args.contact_sheet_batch_size,
        )
    except FinalCatalogPackagingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"ok: packaged final catalog at {final_root}")
    print(f"  cases ok: {manifest['summary']['ok']} / {manifest['summary']['total']}")
    for sheet in manifest["contact_sheets"]["sheets"]:
        print(f"  contact sheet: {sheet['path']}")


if __name__ == "__main__":
    main()
