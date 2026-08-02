"""Build a static storefront bundle from ``final_catalog/catalog.json``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from cloth_store.services.catalog import CatalogService
from cloth_store.services.styling import StylingResolver

DEFAULT_STOREFRONT_JSON = Path("final_catalog/storefront.json")
DEFAULT_CATALOG_JSON = Path("final_catalog/catalog.json")
DEFAULT_FINAL_ROOT = Path("final_catalog")
DEFAULT_SELFIES_PREFIX = "/data"
DEFAULT_ASSETS_PREFIX = "/final_catalog"


def build_storefront_bundle(
    *,
    repo_root: Path,
    catalog_json_path: Path | None = None,
    final_catalog_root: Path | None = None,
    selfies_url_prefix: str = DEFAULT_SELFIES_PREFIX,
    assets_url_prefix: str = DEFAULT_ASSETS_PREFIX,
    neck_down_selfies_only: bool = False,
) -> dict[str, Any]:
    """Pre-compute catalogue views, styling, and outfit data for the static website."""
    root = repo_root.resolve()
    catalog_path = (root / (catalog_json_path or DEFAULT_CATALOG_JSON)).resolve()
    catalog_root = (root / (final_catalog_root or DEFAULT_FINAL_ROOT)).resolve()

    catalog_service = CatalogService(
        catalog_json_path=catalog_path,
        final_catalog_root=catalog_root,
        assets_url_prefix=assets_url_prefix,
    )
    styling_resolver = StylingResolver(
        catalog_service=catalog_service,
        repo_root=root,
        selfies_url_prefix=selfies_url_prefix,
        refocus_selfies_url_prefix=(
            "/final_selfies"
            if selfies_url_prefix.rstrip("/") == DEFAULT_SELFIES_PREFIX.rstrip("/")
            else selfies_url_prefix
        ),
        neck_down_selfies_only=neck_down_selfies_only,
    )

    items: list[dict[str, Any]] = []
    styling_by_id: dict[str, dict[str, Any]] = {}

    browse = catalog_service.browse()
    for item_view in browse.items:
        item_dict = {
            "catalog_id": item_view.catalog_id,
            "display_name": item_view.display_name,
            "role": item_view.role,
            "display_category": item_view.display_category,
            "fixture": item_view.fixture,
            "description": item_view.description,
            "labels": [{"kind": label.kind, "value": label.value} for label in item_view.labels],
            "image_url": item_view.image_url,
            "garment_class": item_view.garment_class,
            "tags": list(item_view.tags),
        }
        items.append(item_dict)

        styling = styling_resolver.resolve_for_catalog_item(item_view.catalog_id)
        if styling is not None:
            styling_by_id[item_view.catalog_id] = styling.to_dict()

    outfit_candidates = [
        candidate.to_dict() for candidate in styling_resolver.list_outfit_candidates()
    ]
    lucky_candidates = [look.to_dict() for look in styling_resolver.list_lucky_look_candidates()]

    return {
        "schema_version": 1,
        "catalog_available": catalog_service.is_available,
        "total_items": len(items),
        "items": items,
        "styling": styling_by_id,
        "outfit_candidates": outfit_candidates,
        "lucky_look_candidates": lucky_candidates,
        "lucky_look_candidate_counts": styling_resolver.lucky_look_candidate_counts(),
    }


def write_storefront_bundle(
    bundle: dict[str, Any],
    *,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the static storefront bundle from final_catalog/catalog.json.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_STOREFRONT_JSON,
        help="Output path for storefront.json",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    output_path = args.output if args.output.is_absolute() else (repo_root / args.output).resolve()

    bundle = build_storefront_bundle(repo_root=repo_root)
    write_storefront_bundle(bundle, output_path=output_path)
    print(f"Wrote {output_path} ({bundle['total_items']} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
