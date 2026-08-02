"""Batch packaging for neck-down privacy selfie variants."""

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
from cloth_store.selfie_final_packaging import repo_relative
from cloth_store.selfie_privacy_crop import (
    DEFAULT_FINAL_SELFIES_ROOT,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_OVERRIDES_PATH,
    NECK_DOWN_METHOD,
    NECK_DOWN_VARIANT,
    PRIVACY_QC_FAIL,
    PRIVACY_QC_LIMITATION,
    PRIVACY_QC_PASS,
    PRIVACY_QC_USER_APPROVED,
    PrivacyCropBatchResult,
    process_fixtures_privacy_crop,
)

DEFAULT_PRIVACY_CONTACT_DIR = Path("contact_sheets_privacy")
DEFAULT_QC_REPORT_NAME = "privacy_qc_report.json"


class SelfiePrivacyPackagingError(RuntimeError):
    """Raised when privacy packaging cannot proceed safely."""


def _contact_sheet_batch_filename(start: int, end: int) -> str:
    return f"outfits_{start:02d}-{end:02d}_neck_down.jpg"


def _load_thumb(path: Path, *, width: int, height: int) -> Image.Image:
    with Image.open(path) as image:
        panel = image.convert("RGB")
        panel.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), (24, 24, 24))
        offset = ((width - panel.width) // 2, (height - panel.height) // 2)
        canvas.paste(panel, offset)
        return canvas


def render_privacy_contact_sheet(
    *,
    records: list[dict[str, Any]],
    repo_root: Path,
    output_path: Path,
    thumb_w: int = 240,
    thumb_h: int = 300,
) -> None:
    """Render source variant | crop_neck_down rows for up to four outfits."""
    columns = ("source_variant", "crop_neck_down")
    label_font = load_font(20)
    header_font = load_font(18)
    header_h = 24
    row_label_h = 22
    margin = 10
    cols = len(columns)
    rows = len(records)
    sheet_w = margin + cols * (thumb_w + margin)
    sheet_h = margin + header_h + rows * (row_label_h + thumb_h + margin) + margin
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)

    for col_index, label in enumerate(columns):
        x = margin + col_index * (thumb_w + margin)
        draw.text((x, margin), label, fill=(210, 210, 210), font=header_font)

    y = margin + header_h
    for record in records:
        fixture_id = record["fixture_id"]
        status = record.get("qc", {}).get("status", PRIVACY_QC_PASS)
        suffix = ""
        if status == PRIVACY_QC_LIMITATION:
            suffix = " [limitation]"
        elif status == PRIVACY_QC_FAIL:
            suffix = " [fail]"
        elif status == PRIVACY_QC_USER_APPROVED:
            suffix = " [user_approved]"
        draw.text((margin, y), f"{fixture_id}{suffix}", fill=(240, 240, 240), font=label_font)
        y += row_label_h

        source_path = repo_root / record["source_variant_path"]
        neck_down_path = repo_root / record["privacy_variant_path"]
        panels = (source_path, neck_down_path)
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


def build_privacy_contact_sheets(
    *,
    repo_root: Path,
    final_root: Path,
    records: list[dict[str, Any]],
    batch_size_outfits: int = 4,
) -> dict[str, Any]:
    sheets_dir = final_root / DEFAULT_PRIVACY_CONTACT_DIR
    sheets_dir.mkdir(parents=True, exist_ok=True)
    sheet_records: list[dict[str, Any]] = []

    for batch_start in range(0, len(records), batch_size_outfits):
        batch = records[batch_start : batch_start + batch_size_outfits]
        start_num = fixture_number(batch[0]["fixture_id"])
        end_num = fixture_number(batch[-1]["fixture_id"])
        filename = _contact_sheet_batch_filename(start_num, end_num)
        output_path = sheets_dir / filename
        render_privacy_contact_sheet(
            records=batch,
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

    return {
        "batch_size_outfits": batch_size_outfits,
        "directory": repo_relative(repo_root, sheets_dir),
        "sheets": sheet_records,
    }


def build_privacy_qc_report(
    *,
    repo_root: Path,
    final_root: Path,
    records: list[dict[str, Any]],
    batch: PrivacyCropBatchResult,
) -> dict[str, Any]:
    summary = {
        PRIVACY_QC_PASS: 0,
        PRIVACY_QC_LIMITATION: 0,
        PRIVACY_QC_FAIL: 0,
        PRIVACY_QC_USER_APPROVED: 0,
    }
    fixtures: list[dict[str, Any]] = []
    for record in records:
        qc = record.get("qc", {})
        status = qc.get("status", PRIVACY_QC_PASS)
        summary[status] = summary.get(status, 0) + 1
        fixtures.append(
            {
                "fixture_id": record["fixture_id"],
                "status": status,
                "notes": qc.get("notes", []),
                "source_variant": record.get("source_variant"),
                "face_bottom_cutoff_y_normalized": record.get("face_bottom_cutoff", {}).get(
                    "y_normalized"
                ),
                "privacy_variant_path": record.get("privacy_variant_path"),
                "privacy_variant_sha256": record.get("privacy_variant_sha256"),
            }
        )

    report = {
        "privacy_method": NECK_DOWN_METHOD,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "fixture_count": len(records),
        "summary": summary,
        "processed": batch.processed,
        "reused": batch.reused,
        "failed": batch.failed,
        "limitations": batch.limitations,
        "fixtures": fixtures,
    }
    report_path = final_root / DEFAULT_QC_REPORT_NAME
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = repo_relative(repo_root, report_path)
    return report


def _copy_privacy_variant(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise SelfiePrivacyPackagingError(f"missing privacy variant source: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return sha256_file(destination)


def package_privacy_fixture(
    *,
    repo_root: Path,
    final_root: Path,
    bench_root: Path,
    fixture_id: str,
) -> dict[str, Any]:
    bench_metadata_path = bench_root / fixture_id / f"{NECK_DOWN_VARIANT}.metadata.json"
    if not bench_metadata_path.is_file():
        raise SelfiePrivacyPackagingError(
            f"missing bench privacy metadata for {fixture_id}: {bench_metadata_path}"
        )
    privacy_metadata = json.loads(bench_metadata_path.read_text(encoding="utf-8"))
    if privacy_metadata.get("privacy_method") != NECK_DOWN_METHOD:
        raise SelfiePrivacyPackagingError(f"unexpected privacy method for {fixture_id}")

    fixture_dir = final_root / fixture_id
    fixture_dir.mkdir(parents=True, exist_ok=True)
    bench_image = bench_root / fixture_id / f"{NECK_DOWN_VARIANT}.jpg"
    destination = fixture_dir / f"{NECK_DOWN_VARIANT}.jpg"
    variant_sha256 = _copy_privacy_variant(bench_image, destination)

    final_metadata_path = fixture_dir / "metadata.json"
    if not final_metadata_path.is_file():
        raise SelfiePrivacyPackagingError(f"missing final metadata for {fixture_id}")
    final_metadata = json.loads(final_metadata_path.read_text(encoding="utf-8"))

    privacy_block = {
        "method": NECK_DOWN_METHOD,
        "variant": NECK_DOWN_VARIANT,
        "path": repo_relative(repo_root, destination),
        "sha256": variant_sha256,
        "source_variant": privacy_metadata.get("source_variant"),
        "source_variant_sha256": privacy_metadata.get("source_variant_sha256"),
        "face_bottom_cutoff": privacy_metadata.get("face_bottom_cutoff"),
        "bench_metadata_path": repo_relative(repo_root, bench_metadata_path),
        "qc": privacy_metadata.get("qc", {}),
    }
    if privacy_metadata.get("user_approved"):
        privacy_block["user_approved"] = True
    final_metadata["privacy_variant"] = privacy_block
    final_metadata_path.write_text(json.dumps(final_metadata, indent=2) + "\n", encoding="utf-8")

    return {
        "fixture_id": fixture_id,
        "privacy_variant_path": privacy_block["path"],
        "privacy_variant_sha256": variant_sha256,
        "source_variant": privacy_metadata.get("source_variant"),
        "source_variant_path": privacy_metadata.get("source_refocused_path"),
        "face_bottom_cutoff": privacy_metadata.get("face_bottom_cutoff", {}),
        "qc": privacy_metadata.get("qc", {}),
        "metadata_path": repo_relative(repo_root, final_metadata_path),
    }


def update_manifest_with_privacy(
    *,
    repo_root: Path,
    final_root: Path,
    privacy_records: list[dict[str, Any]],
    contact_sheets: dict[str, Any],
    qc_report: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = final_root / "manifest.json"
    if not manifest_path.is_file():
        raise SelfiePrivacyPackagingError("missing final_selfies/manifest.json")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id = {item["fixture_id"]: item for item in manifest.get("fixtures", [])}
    for record in privacy_records:
        fixture = by_id.get(record["fixture_id"])
        if fixture is None:
            raise SelfiePrivacyPackagingError(
                f"fixture missing from manifest: {record['fixture_id']}"
            )
        fixture["privacy_variant"] = {
            "variant": NECK_DOWN_VARIANT,
            "path": record["privacy_variant_path"],
            "sha256": record["privacy_variant_sha256"],
            "source_variant": record["source_variant"],
            "face_bottom_cutoff_y_normalized": record["face_bottom_cutoff"].get("y_normalized"),
            "qc_status": record["qc"].get("status", PRIVACY_QC_PASS),
        }

    manifest["privacy"] = {
        "method": NECK_DOWN_METHOD,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "fixture_count": len(privacy_records),
        "contact_sheets": contact_sheets,
        "qc_report_path": qc_report["report_path"],
        "qc_summary": qc_report["summary"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["manifest_path"] = repo_relative(repo_root, manifest_path)
    return manifest


def validate_privacy_outputs(
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
    privacy = manifest.get("privacy")
    if not privacy:
        errors.append("manifest missing privacy block")
        return errors

    fixtures = manifest.get("fixtures", [])
    if fixture_ids is not None:
        allowed = set(fixture_ids)
        fixtures = [item for item in fixtures if item.get("fixture_id") in allowed]

    for item in fixtures:
        fixture_id = item["fixture_id"]
        block = item.get("privacy_variant")
        if not block:
            errors.append(f"{fixture_id}: missing privacy_variant in manifest")
            continue
        rel = block.get("path")
        if not rel:
            errors.append(f"{fixture_id}: missing privacy variant path")
            continue
        path = repo_root / rel
        if not path.is_file():
            errors.append(f"{fixture_id}: missing privacy variant file {rel}")
            continue
        expected = block.get("sha256")
        if expected and sha256_file(path) != expected:
            errors.append(f"{fixture_id}: privacy variant hash mismatch")
        if block.get("qc_status") == PRIVACY_QC_FAIL:
            errors.append(f"{fixture_id}: privacy QC marked fail")

        for name in ("crop_only", "crop_refocused"):
            variant_rel = item.get("variants", {}).get(name)
            if not variant_rel:
                continue
            variant_path = repo_root / variant_rel
            if not variant_path.is_file():
                errors.append(f"{fixture_id}: missing original variant {name}")
                continue
            expected_variant = item.get("variant_sha256", {}).get(name)
            if expected_variant and sha256_file(variant_path) != expected_variant:
                errors.append(f"{fixture_id}: original variant hash changed for {name}")

    for sheet in privacy.get("contact_sheets", {}).get("sheets", []):
        sheet_path = repo_root / sheet["path"]
        if not sheet_path.is_file():
            errors.append(f"missing privacy contact sheet: {sheet['path']}")
        elif sheet.get("sha256") and sha256_file(sheet_path) != sheet["sha256"]:
            errors.append(f"privacy contact sheet hash mismatch: {sheet['path']}")

    qc_path = privacy.get("qc_report_path")
    if qc_path and not (repo_root / qc_path).is_file():
        errors.append(f"missing privacy QC report: {qc_path}")

    return errors


def run_privacy_pipeline(
    *,
    repo_root: Path,
    bench_root: Path,
    final_root: Path,
    fixture_ids: list[str],
    overrides_path: Path | None = None,
    continue_on_error: bool = True,
    force: bool = False,
    batch_size_outfits: int = 4,
) -> dict[str, Any]:
    batch = process_fixtures_privacy_crop(
        fixture_ids,
        repo_root=repo_root,
        candidate_root=bench_root,
        overrides_path=overrides_path,
        continue_on_error=continue_on_error,
        force=force,
    )
    if batch.failed:
        failed = ", ".join(f"{key}: {value}" for key, value in batch.failed.items())
        raise SelfiePrivacyPackagingError(f"privacy crop failures: {failed}")

    privacy_records: list[dict[str, Any]] = []
    for fixture_id in fixture_ids:
        privacy_records.append(
            package_privacy_fixture(
                repo_root=repo_root,
                final_root=final_root,
                bench_root=bench_root,
                fixture_id=fixture_id,
            )
        )

    contact_sheets = build_privacy_contact_sheets(
        repo_root=repo_root,
        final_root=final_root,
        records=privacy_records,
        batch_size_outfits=batch_size_outfits,
    )
    qc_report = build_privacy_qc_report(
        repo_root=repo_root,
        final_root=final_root,
        records=privacy_records,
        batch=batch,
    )
    manifest = update_manifest_with_privacy(
        repo_root=repo_root,
        final_root=final_root,
        privacy_records=privacy_records,
        contact_sheets=contact_sheets,
        qc_report=qc_report,
    )
    manifest["privacy_batch"] = {
        "processed": batch.processed,
        "reused": batch.reused,
        "limitations": batch.limitations,
    }
    manifest["privacy_qc_report"] = qc_report
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate neck-down privacy crops for mirror selfies and package them "
            "into final_selfies/ as an optional variant."
        )
    )
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument(
        "--bench-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Bench candidate root.",
    )
    parser.add_argument(
        "--final-root",
        default=str(DEFAULT_FINAL_SELFIES_ROOT),
        help="Final deliverable root.",
    )
    parser.add_argument(
        "--overrides-path",
        default=str(DEFAULT_OVERRIDES_PATH),
        help="Per-fixture reviewed cutoff overrides JSON.",
    )
    parser.add_argument("--fixture", action="append", dest="fixtures", help="Fixture id.")
    parser.add_argument("--from-fixture", type=int, help="Inclusive range start.")
    parser.add_argument("--to-fixture", type=int, help="Inclusive range end.")
    parser.add_argument(
        "--contact-sheet-batch-size",
        type=int,
        default=4,
        help="Outfits per privacy contact sheet (default: 4).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing privacy outputs and exit.",
    )
    parser.add_argument(
        "--bench-only",
        action="store_true",
        help="Generate bench candidates only; skip final_selfies packaging.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even when existing privacy outputs match inputs.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help="Record failures and continue other fixtures (default: true).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    bench_root = repo_root / args.bench_root
    final_root = repo_root / args.final_root
    overrides_path = repo_root / args.overrides_path

    if args.from_fixture is not None or args.to_fixture is not None:
        fixture_ids = resolve_plan1_fixtures(
            from_fixture=args.from_fixture,
            to_fixture=args.to_fixture,
        )
    elif args.fixtures:
        fixture_ids = args.fixtures
    else:
        fixture_ids = resolve_plan1_fixtures(from_fixture=1, to_fixture=31)

    if args.validate_only:
        errors = validate_privacy_outputs(
            repo_root=repo_root,
            final_root=final_root,
            fixture_ids=fixture_ids,
        )
        if errors:
            for error in errors:
                print(f"validation error: {error}", file=sys.stderr)
            raise SystemExit(1)
        print(f"privacy validation ok: {len(fixture_ids)} fixtures")
        return

    try:
        if args.bench_only:
            batch = process_fixtures_privacy_crop(
                fixture_ids,
                repo_root=repo_root,
                candidate_root=bench_root,
                overrides_path=overrides_path,
                continue_on_error=args.continue_on_error,
                force=args.force,
            )
            print(
                f"processed={len(batch.processed)} reused={len(batch.reused)} "
                f"failed={len(batch.failed)} limitations={len(batch.limitations)}"
            )
            if batch.failed:
                raise SystemExit(1)
            return

        manifest = run_privacy_pipeline(
            repo_root=repo_root,
            bench_root=bench_root,
            final_root=final_root,
            fixture_ids=fixture_ids,
            overrides_path=overrides_path,
            continue_on_error=args.continue_on_error,
            force=args.force,
            batch_size_outfits=args.contact_sheet_batch_size,
        )
        batch = manifest["privacy_batch"]
        print(
            f"processed={len(batch['processed'])} reused={len(batch['reused'])} "
            f"limitations={len(batch['limitations'])} "
            f"fixtures={manifest['privacy']['fixture_count']}"
        )
        for sheet in manifest["privacy"]["contact_sheets"]["sheets"]:
            print(f"  privacy contact sheet: {sheet['path']}")
        print(f"privacy QC report: {manifest['privacy']['qc_report_path']}")
        print(f"manifest: {manifest['manifest_path']}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
