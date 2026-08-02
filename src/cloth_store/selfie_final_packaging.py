"""Self-contained final selfie refocus packaging for review and downstream use."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from cloth_store.catalog_hash import sha256_file
from cloth_store.catalog_paths import fixture_number, resolve_plan1_fixtures
from cloth_store.sam_masks import load_font
from cloth_store.selfie_refocus import (
    DEFAULT_JSON_DIR,
    DEFAULT_OUTPUT_ROOT,
    REFOCUS_METHOD,
    assess_review_required,
    load_fixture_metadata,
    process_fixtures,
)

DEFAULT_FINAL_ROOT = Path("final_selfies")
DEFAULT_BENCH_ROOT = DEFAULT_OUTPUT_ROOT

FINAL_VARIANT_NAMES = ("crop_only", "crop_refocused")


class SelfieFinalPackagingError(RuntimeError):
    """Raised when final selfie packaging cannot proceed safely."""


def repo_relative(repo_root: Path, path: Path | str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return str(candidate)
    try:
        return str(candidate.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(candidate)


def _contact_sheet_batch_filename(start: int, end: int) -> str:
    return f"outfits_{start:02d}-{end:02d}.jpg"


def _load_thumb(path: Path, *, width: int, height: int) -> Image.Image:
    with Image.open(path) as image:
        panel = image.convert("RGB")
        panel.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), (24, 24, 24))
        offset = ((width - panel.width) // 2, (height - panel.height) // 2)
        canvas.paste(panel, offset)
        return canvas


def render_selfie_contact_sheet(
    *,
    fixtures: list[dict[str, Any]],
    repo_root: Path,
    output_path: Path,
    thumb_w: int = 240,
    thumb_h: int = 300,
) -> None:
    """Render original | crop_only | crop_refocused rows for up to four outfits."""
    columns = ("original", "crop_only", "crop_refocused")
    label_font = load_font(20)
    header_font = load_font(18)
    header_h = 24
    row_label_h = 22
    margin = 10
    cols = len(columns)
    rows = len(fixtures)
    sheet_w = margin + cols * (thumb_w + margin)
    sheet_h = margin + header_h + rows * (row_label_h + thumb_h + margin) + margin
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)

    for col_index, label in enumerate(columns):
        x = margin + col_index * (thumb_w + margin)
        draw.text((x, margin), label, fill=(210, 210, 210), font=header_font)

    y = margin + header_h
    for fixture in fixtures:
        fixture_id = fixture["fixture_id"]
        status = ""
        if fixture.get("review_required"):
            status = " [review_required]"
        draw.text((margin, y), f"{fixture_id}{status}", fill=(240, 240, 240), font=label_font)
        y += row_label_h

        source_path = repo_root / fixture["source_path"]
        crop_only_path = repo_root / fixture["variants"]["crop_only"]
        crop_refocused_path = repo_root / fixture["variants"]["crop_refocused"]
        panels = (source_path, crop_only_path, crop_refocused_path)

        for col_index, panel_path in enumerate(panels):
            x = margin + col_index * (thumb_w + margin)
            if panel_path.is_file():
                sheet.paste(_load_thumb(panel_path, width=thumb_w, height=thumb_h), (x, y))
            else:
                draw.rectangle(
                    [x, y, x + thumb_w, y + thumb_h],
                    outline=(120, 120, 120),
                )
                draw.text((x + 8, y + 8), "missing", fill=(160, 160, 160), font=header_font)
        y += thumb_h + margin

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def build_batched_contact_sheets(
    *,
    repo_root: Path,
    final_root: Path,
    fixtures: list[dict[str, Any]],
    batch_size_outfits: int = 4,
) -> dict[str, Any]:
    if batch_size_outfits < 1:
        raise SelfieFinalPackagingError("batch_size_outfits must be >= 1")

    sheets_dir = final_root / "contact_sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)
    sheet_records: list[dict[str, Any]] = []

    for batch_start in range(0, len(fixtures), batch_size_outfits):
        batch = fixtures[batch_start : batch_start + batch_size_outfits]
        start_num = fixture_number(batch[0]["fixture_id"])
        end_num = fixture_number(batch[-1]["fixture_id"])
        filename = _contact_sheet_batch_filename(start_num, end_num)
        output_path = sheets_dir / filename
        render_selfie_contact_sheet(
            fixtures=batch,
            repo_root=repo_root,
            output_path=output_path,
        )
        sheet_records.append(
            {
                "path": repo_relative(repo_root, output_path),
                "filename": filename,
                "outfit_range": {"start": start_num, "end": end_num},
                "outfits": [item["fixture_id"] for item in batch],
                "fixture_count": len(batch),
                "sha256": sha256_file(output_path),
            }
        )

    legacy_monolith = final_root / "contact_sheet.jpg"
    if legacy_monolith.is_file():
        legacy_monolith.unlink()

    covered = [fixture_id for sheet in sheet_records for fixture_id in sheet["outfits"]]
    expected = [item["fixture_id"] for item in fixtures]
    if covered != expected:
        raise SelfieFinalPackagingError(
            f"contact sheet batch coverage mismatch: expected {expected}, got {covered}"
        )

    return {
        "batch_size_outfits": batch_size_outfits,
        "directory": repo_relative(repo_root, sheets_dir),
        "sheets": sheet_records,
    }


def _copy_variant(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise SelfieFinalPackagingError(f"missing variant source: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return sha256_file(destination)


def package_fixture_record(
    *,
    repo_root: Path,
    final_root: Path,
    bench_metadata: dict[str, Any],
    bench_root: Path,
) -> dict[str, Any]:
    fixture_id = bench_metadata["fixture_id"]
    fixture_dir = final_root / fixture_id
    fixture_dir.mkdir(parents=True, exist_ok=True)

    variants: dict[str, str] = {}
    variant_hashes: dict[str, str] = {}
    for name in FINAL_VARIANT_NAMES:
        rel = bench_metadata["variants"][name]
        source = (repo_root / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
        if not source.is_file():
            source = bench_root / fixture_id / f"{name}.jpg"
        destination = fixture_dir / f"{name}.jpg"
        variant_hashes[name] = _copy_variant(source, destination)
        variants[name] = repo_relative(repo_root, destination)

    person_bbox = bench_metadata["person_bbox"]
    metrics = bench_metadata["metrics"]
    review_required = bench_metadata.get("review_required")
    review_reason = bench_metadata.get("review_reason")
    if review_required is None:
        review_required, review_reason = assess_review_required(
            person_bbox=person_bbox,
            metrics=metrics,
        )
    recommended = bench_metadata.get("recommended_variant") or (
        "crop_only" if review_required else "crop_refocused"
    )

    record = {
        "fixture_id": fixture_id,
        "status": "ok",
        "review_required": review_required,
        "review_reason": review_reason,
        "recommended_variant": recommended,
        "source_path": bench_metadata["source_path"],
        "source_sha256": bench_metadata["source_sha256"],
        "person_bbox": person_bbox,
        "crop": bench_metadata["crop"],
        "metrics": metrics,
        "variants": variants,
        "variant_sha256": variant_hashes,
        "parameters": bench_metadata.get("parameters", {}),
        "bench_artifacts": {
            "person_mask": bench_metadata.get("artifacts", {}).get("person_mask"),
            "bbox_mask_overlay": bench_metadata.get("artifacts", {}).get("bbox_mask_overlay"),
            "comparison_sheet": bench_metadata.get("artifacts", {}).get("comparison_sheet"),
        },
        "generated_or_reused": bench_metadata.get("generated_or_reused", "processed"),
    }
    metadata_path = fixture_dir / "metadata.json"
    metadata_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    record["metadata_path"] = repo_relative(repo_root, metadata_path)
    return record


def validate_final_selfies(
    *,
    repo_root: Path,
    final_root: Path,
    fixture_ids: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    manifest_path = final_root / "manifest.json"
    if not manifest_path.is_file():
        return ["missing manifest.json"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = manifest.get("fixtures", [])
    if fixture_ids is not None:
        allowed = set(fixture_ids)
        fixtures = [item for item in fixtures if item.get("fixture_id") in allowed]

    for item in fixtures:
        fixture_id = item["fixture_id"]
        for name in FINAL_VARIANT_NAMES:
            rel = item.get("variants", {}).get(name)
            if not rel:
                errors.append(f"{fixture_id}: missing variant path for {name}")
                continue
            path = repo_root / rel
            if not path.is_file():
                errors.append(f"{fixture_id}: missing variant file {rel}")
                continue
            expected = item.get("variant_sha256", {}).get(name)
            if expected and sha256_file(path) != expected:
                errors.append(f"{fixture_id}: hash mismatch for {name}")

        params = item.get("parameters", {})
        if params.get("refocus_method") != REFOCUS_METHOD:
            errors.append(f"{fixture_id}: refocus_method must be {REFOCUS_METHOD}")

        source_rel = item.get("source_path")
        if source_rel:
            source_path = repo_root / source_rel
            if source_path.is_file():
                if item.get("source_sha256") != sha256_file(source_path):
                    errors.append(f"{fixture_id}: source_sha256 mismatch")
            else:
                errors.append(f"{fixture_id}: missing source photo {source_rel}")

    contact_sheets = manifest.get("contact_sheets", {})
    for sheet in contact_sheets.get("sheets", []):
        sheet_path = repo_root / sheet["path"]
        if not sheet_path.is_file():
            errors.append(f"missing contact sheet: {sheet['path']}")
        elif sheet.get("sha256") and sha256_file(sheet_path) != sheet["sha256"]:
            errors.append(f"contact sheet hash mismatch: {sheet['path']}")

    return errors


def build_readme(*, manifest: dict[str, Any]) -> str:
    contact_sheets = manifest.get("contact_sheets", {})
    sheet_lines = "\n".join(
        f"    - `{sheet['path']}` ({sheet['outfit_range']['start']}–{sheet['outfit_range']['end']})"
        for sheet in contact_sheets.get("sheets", [])
    )
    return f"""# Final selfies (blur-only refocus)

Self-contained mirror-selfie portrait crops with blur-only background refocus for review.
Source photos under `data/` are never modified.

## Layout

```
final_selfies/
  manifest.json
  README.md
  contact_sheets/
{sheet_lines}
  outfit_N/
    crop_only.jpg
    crop_refocused.jpg
    metadata.json
```

Person masks and bench overlays remain under `bench/selfie_refocus/candidates/` and are
referenced from each fixture's `bench_artifacts` block.

## Regenerate

```bash
bench/selfie_refocus/run.sh --from-fixture 1 --to-fixture 31
uv run cloth-store-selfie-final-packaging --repo-root . --from-fixture 1 --to-fixture 31
uv run cloth-store-selfie-final-packaging --repo-root . --validate-only
```

## Review policy

Fixtures marked `review_required: true` should use `crop_only` until manually corrected.
Blur-only refocus preserves background color and brightness (`refocus_method: {REFOCUS_METHOD}`).
"""


def package_final_selfies(
    *,
    repo_root: str | Path,
    final_root: str | Path = DEFAULT_FINAL_ROOT,
    bench_root: str | Path = DEFAULT_BENCH_ROOT,
    json_dir: str | Path = DEFAULT_JSON_DIR,
    fixture_ids: list[str],
    batch_size_outfits: int = 4,
    force: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    final_path = Path(final_root).expanduser().resolve()
    bench_path = Path(bench_root).expanduser().resolve()
    final_path.mkdir(parents=True, exist_ok=True)

    packaged: list[dict[str, Any]] = []
    skipped: list[str] = []
    missing_bench: list[str] = []

    for fixture_id in fixture_ids:
        bench_metadata_path = bench_path / fixture_id / "metadata.json"
        if not bench_metadata_path.is_file():
            missing_bench.append(fixture_id)
            continue

        bench_metadata = load_fixture_metadata(bench_metadata_path)
        if bench_metadata.get("parameters", {}).get("refocus_method") != REFOCUS_METHOD:
            missing_bench.append(fixture_id)
            continue

        final_metadata_path = final_path / fixture_id / "metadata.json"
        if not force and final_metadata_path.is_file():
            existing = json.loads(final_metadata_path.read_text(encoding="utf-8"))
            if (
                existing.get("source_sha256") == bench_metadata.get("source_sha256")
                and existing.get("parameters", {}).get("refocus_method") == REFOCUS_METHOD
            ):
                bench_variants = bench_metadata.get("variants", {})
                existing_variants = existing.get("variants", {})
                if all(
                    (root / existing_variants.get(name, "")).is_file()
                    for name in FINAL_VARIANT_NAMES
                ):
                    variant_hashes = {
                        name: sha256_file(root / existing_variants[name])
                        for name in FINAL_VARIANT_NAMES
                    }
                    bench_hashes = {
                        name: sha256_file(
                            (root / bench_variants[name])
                            if (root / bench_variants[name]).is_file()
                            else bench_path / fixture_id / f"{name}.jpg"
                        )
                        for name in FINAL_VARIANT_NAMES
                    }
                    if variant_hashes == bench_hashes:
                        existing["generated_or_reused"] = "reused"
                        packaged.append(existing)
                        skipped.append(fixture_id)
                        continue

        record = package_fixture_record(
            repo_root=root,
            final_root=final_path,
            bench_metadata=bench_metadata,
            bench_root=bench_path,
        )
        packaged.append(record)

    if missing_bench:
        raise SelfieFinalPackagingError(
            "missing or invalid bench metadata for: " + ", ".join(missing_bench)
        )

    contact_sheets = build_batched_contact_sheets(
        repo_root=root,
        final_root=final_path,
        fixtures=packaged,
        batch_size_outfits=batch_size_outfits,
    )

    review_required = [item["fixture_id"] for item in packaged if item.get("review_required")]
    manifest = {
        "namespace": "final_selfies",
        "refocus_method": REFOCUS_METHOD,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "fixture_count": len(packaged),
        "review_required_count": len(review_required),
        "review_required_fixtures": review_required,
        "fixtures": packaged,
        "contact_sheets": contact_sheets,
        "bench_root": repo_relative(root, bench_path),
    }
    manifest_path = final_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (final_path / "README.md").write_text(build_readme(manifest=manifest), encoding="utf-8")
    manifest["manifest_path"] = repo_relative(root, manifest_path)
    manifest["skipped_fixtures"] = skipped
    return manifest


def run_selfie_pipeline(
    *,
    repo_root: str | Path,
    bench_root: str | Path = DEFAULT_BENCH_ROOT,
    final_root: str | Path = DEFAULT_FINAL_ROOT,
    json_dir: str | Path = DEFAULT_JSON_DIR,
    fixture_ids: list[str],
    continue_on_error: bool = True,
    force: bool = False,
    batch_size_outfits: int = 4,
) -> dict[str, Any]:
    """Process bench candidates then package final deliverables."""
    batch = process_fixtures(
        fixture_ids,
        repo_root=repo_root,
        output_root=bench_root,
        json_dir=json_dir,
        continue_on_error=continue_on_error,
        force=force,
    )
    manifest = package_final_selfies(
        repo_root=repo_root,
        final_root=final_root,
        bench_root=bench_root,
        json_dir=json_dir,
        fixture_ids=fixture_ids,
        batch_size_outfits=batch_size_outfits,
        force=force,
    )
    manifest["batch"] = batch
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package bench selfie refocus outputs into final_selfies/ deliverable."
    )
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument(
        "--final-root",
        default=str(DEFAULT_FINAL_ROOT),
        help="Final deliverable root (default: final_selfies).",
    )
    parser.add_argument(
        "--bench-root",
        default=str(DEFAULT_BENCH_ROOT),
        help="Bench candidate root (default: bench/selfie_refocus/candidates).",
    )
    parser.add_argument(
        "--json-dir",
        default=str(DEFAULT_JSON_DIR),
        help="Plan1 localization JSON directory.",
    )
    parser.add_argument("--fixture", action="append", dest="fixtures", help="Fixture id.")
    parser.add_argument("--from-fixture", type=int, help="Inclusive range start.")
    parser.add_argument("--to-fixture", type=int, help="Inclusive range end.")
    parser.add_argument(
        "--contact-sheet-batch-size",
        type=int,
        default=4,
        help="Outfits per contact sheet (default: 4).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing final_selfies/ manifest and exit.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Repackage even when existing final outputs match bench hashes.",
    )
    parser.add_argument(
        "--run-bench",
        action="store_true",
        help="Run bench refocus processing before packaging.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help="Record bench failures and continue other fixtures (default: true).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    final_root = repo_root / args.final_root

    if args.validate_only:
        if args.from_fixture is not None or args.to_fixture is not None:
            fixture_ids = resolve_plan1_fixtures(
                from_fixture=args.from_fixture,
                to_fixture=args.to_fixture,
            )
        elif args.fixtures:
            fixture_ids = args.fixtures
        else:
            fixture_ids = None
        errors = validate_final_selfies(
            repo_root=repo_root,
            final_root=final_root,
            fixture_ids=fixture_ids,
        )
        if errors:
            for error in errors:
                print(f"validation error: {error}", file=sys.stderr)
            raise SystemExit(1)
        print(f"validation ok: {final_root}")
        return

    try:
        if args.from_fixture is not None or args.to_fixture is not None:
            fixture_ids = resolve_plan1_fixtures(
                from_fixture=args.from_fixture,
                to_fixture=args.to_fixture,
            )
        elif args.fixtures:
            fixture_ids = args.fixtures
        else:
            raise ValueError("specify --fixture, or --from-fixture and --to-fixture")

        if args.run_bench:
            manifest = run_selfie_pipeline(
                repo_root=repo_root,
                bench_root=repo_root / args.bench_root,
                final_root=final_root,
                json_dir=repo_root / args.json_dir,
                fixture_ids=fixture_ids,
                continue_on_error=args.continue_on_error,
                force=args.force,
                batch_size_outfits=args.contact_sheet_batch_size,
            )
            batch = manifest["batch"]
            print(
                f"processed={len(batch.processed)} reused={len(batch.reused)} "
                f"failed={len(batch.failed)} review={len(batch.review_required)}"
            )
        else:
            manifest = package_final_selfies(
                repo_root=repo_root,
                final_root=final_root,
                bench_root=repo_root / args.bench_root,
                json_dir=repo_root / args.json_dir,
                fixture_ids=fixture_ids,
                batch_size_outfits=args.contact_sheet_batch_size,
                force=args.force,
            )
            print(
                f"packaged={manifest['fixture_count']} skipped={len(manifest['skipped_fixtures'])}"
            )

        for sheet in manifest["contact_sheets"]["sheets"]:
            print(f"  contact sheet: {sheet['path']}")
        print(f"manifest: {manifest['manifest_path']}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
