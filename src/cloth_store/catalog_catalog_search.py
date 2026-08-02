"""Dependency-free lexical search over ``final_catalog/catalog.json``."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloth_store.catalog_catalog_index import DEFAULT_CATALOG_JSON, load_catalog_index
from cloth_store.catalog_paths import CATALOG_ID_ALIASES, resolve_catalog_id

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

FIELD_WEIGHTS: dict[str, int] = {
    "garment_class": 12,
    "colors": 10,
    "material": 8,
    "silhouette_style": 8,
    "pattern": 5,
    "sheen": 4,
    "neckline_collar": 4,
    "closure": 3,
    "tags": 3,
    "search_text": 2,
    "display_name": 2,
    "template_id": 2,
}


@dataclass(frozen=True)
class SearchHit:
    catalog_id: str
    score: int
    display_name: str
    matched_fields: tuple[str, ...]
    matched_tokens: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "score": self.score,
            "display_name": self.display_name,
            "matched_fields": list(self.matched_fields),
            "matched_tokens": list(self.matched_tokens),
        }


def tokenize(text: str) -> list[str]:
    return [token for token in _NON_ALNUM.split(text.lower()) if token]


def _field_tokens(item: dict[str, Any], field_name: str) -> list[str]:
    if field_name == "display_name":
        return tokenize(str(item.get("display_name", "")))
    if field_name == "template_id":
        return tokenize(str(item.get("template", {}).get("template_id", "")))
    if field_name == "tags":
        return [token for tag in item.get("tags", []) for token in tokenize(str(tag))]
    if field_name == "search_text":
        return tokenize(str(item.get("retrieval", {}).get("search_text", "")))
    facet = item.get("facets", {}).get(field_name, {})
    if isinstance(facet, dict):
        value = facet.get("value")
        if isinstance(value, str):
            return tokenize(value)
    if field_name == "garment_class":
        value = item.get("garment_class_normalized")
        if isinstance(value, str):
            return tokenize(value)
    return []


def _matches_filters(
    item: dict[str, Any],
    *,
    role: str | None,
    color: str | None,
    garment_class: str | None,
) -> bool:
    if role is not None and item.get("role") != role:
        return False
    if garment_class is not None:
        normalized = str(item.get("garment_class_normalized", "")).lower()
        if garment_class.lower() not in normalized and garment_class.lower() not in {
            token.lower() for token in item.get("tags", [])
        }:
            return False
    if color is not None:
        colors_field = item.get("facets", {}).get("colors", {})
        value = str(colors_field.get("value", "")).lower() if isinstance(colors_field, dict) else ""
        color_lower = color.lower()
        if color_lower not in value and color_lower not in {
            token.lower() for token in item.get("tags", [])
        }:
            search_text = str(item.get("retrieval", {}).get("search_text", "")).lower()
            if color_lower not in search_text:
                return False
    return True


def _identity_color_boost(item: dict[str, Any], query_tokens: list[str]) -> int:
    if len(item.get("observation_ids", [])) <= 1 or not query_tokens:
        return 0
    alias_colors = item.get("identity", {}).get("alias_color_tokens")
    if not isinstance(alias_colors, list):
        return 0
    color_hits = {str(color).lower() for color in alias_colors}.intersection(query_tokens)
    if not color_hits:
        return 0
    non_color_tokens = [token for token in query_tokens if token not in color_hits]
    if non_color_tokens:
        garment_class = str(item.get("garment_class_normalized", "")).lower()
        item_tokens = set(tokenize(garment_class)) | {
            token.lower() for tag in item.get("tags", []) for token in tokenize(str(tag))
        }
        if not any(token in item_tokens for token in non_color_tokens):
            return 0
    return 25 * len(color_hits)


def _fixture_query_adjustment(item: dict[str, Any], query_tokens: list[str]) -> int:
    """Boost exact outfit-number matches and suppress other fixtures when a number is present."""
    number_tokens = [token for token in query_tokens if token.isdigit()]
    if not number_tokens:
        return 0

    item_numbers: set[str] = set()
    fixture = str(item.get("fixture", ""))
    if fixture.startswith("outfit_"):
        item_numbers.add(fixture.removeprefix("outfit_"))
    for observation_id in item.get("observation_ids", []):
        if isinstance(observation_id, str) and observation_id.startswith("outfit_"):
            parts = observation_id.split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                item_numbers.add(parts[1])

    if item_numbers.intersection(number_tokens):
        return 60
    return -80


def _alias_boost(query_tokens: list[str], item: dict[str, Any]) -> int:
    catalog_id_value = str(item.get("catalog_id", ""))
    legacy_ids = item.get("legacy_catalog_ids", [])
    if not isinstance(legacy_ids, list):
        return 0
    for legacy_id in legacy_ids:
        if not isinstance(legacy_id, str):
            continue
        legacy_tokens = tokenize(legacy_id.replace("_", " "))
        if legacy_tokens and all(token in query_tokens for token in legacy_tokens):
            return 50
    canonical = resolve_catalog_id(catalog_id_value)
    if canonical != catalog_id_value:
        return 0
    for alias_id, target in CATALOG_ID_ALIASES.items():
        if target == catalog_id_value:
            alias_tokens = tokenize(alias_id.replace("_", " "))
            if alias_tokens and all(token in query_tokens for token in alias_tokens):
                return 50
    return 0


def _legacy_role_query_penalty(item: dict[str, Any], query_tokens: list[str]) -> int:
    """Avoid matching dress catalog entries on generic 'top' queries without fixture context."""
    if str(item.get("role")) != "dress" or "top" not in query_tokens or "dress" in query_tokens:
        return 0
    fixture = str(item.get("fixture", ""))
    if not fixture.startswith("outfit_"):
        return 0
    item_number = fixture.removeprefix("outfit_")
    if item_number in query_tokens:
        return 0
    return -120


def search_catalog(
    *,
    payload: dict[str, Any],
    query: str,
    role: str | None = None,
    color: str | None = None,
    garment_class: str | None = None,
    limit: int | None = None,
) -> list[SearchHit]:
    query_tokens = tokenize(query)
    hits: list[SearchHit] = []
    items_by_id = {
        str(item["catalog_id"]): item
        for item in payload.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("catalog_id"), str)
    }

    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        if not _matches_filters(item, role=role, color=color, garment_class=garment_class):
            continue

        score = 0
        matched_fields: set[str] = set()
        matched_tokens: set[str] = set()

        if not query_tokens:
            hits.append(
                SearchHit(
                    catalog_id=str(item["catalog_id"]),
                    score=0,
                    display_name=str(item.get("display_name", "")),
                    matched_fields=(),
                    matched_tokens=(),
                )
            )
            continue

        for field_name, weight in FIELD_WEIGHTS.items():
            field_tokens = _field_tokens(item, field_name)
            if not field_tokens:
                continue
            field_set = set(field_tokens)
            overlap = [token for token in query_tokens if token in field_set]
            if not overlap:
                continue
            score += weight * len(overlap)
            matched_fields.add(field_name)
            matched_tokens.update(overlap)

        if score > 0:
            score += _identity_color_boost(item, query_tokens)
            score += _alias_boost(query_tokens, item)
            score += _fixture_query_adjustment(item, query_tokens)
            score += _legacy_role_query_penalty(item, query_tokens)
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    catalog_id=str(item["catalog_id"]),
                    score=score,
                    display_name=str(item.get("display_name", "")),
                    matched_fields=tuple(sorted(matched_fields)),
                    matched_tokens=tuple(sorted(matched_tokens)),
                )
            )

    hits.sort(
        key=lambda hit: (
            -hit.score,
            0
            if hit.score == 0
            else -len(items_by_id.get(hit.catalog_id, {}).get("observation_ids", ())),
            hit.catalog_id,
        )
    )
    if limit is not None:
        return hits[:limit]
    return hits


def format_hits(hits: list[SearchHit]) -> str:
    if not hits:
        return "No matches."
    lines: list[str] = []
    for index, hit in enumerate(hits, start=1):
        fields = ", ".join(hit.matched_fields) if hit.matched_fields else "filter-only"
        tokens = ", ".join(hit.matched_tokens) if hit.matched_tokens else "-"
        lines.append(
            f"{index}. {hit.catalog_id} score={hit.score} "
            f"name={hit.display_name!r} fields=[{fields}] tokens=[{tokens}]"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lexical search over final_catalog/catalog.json (not semantic/vector search)."
    )
    parser.add_argument("query", nargs="?", default="", help="Search query")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_JSON,
        help="Path to catalog.json",
    )
    parser.add_argument("--role", choices=("top", "bottom", "dress"), default=None)
    parser.add_argument("--color", default=None, help="Filter by dominant color substring")
    parser.add_argument("--class", dest="garment_class", default=None, help="Garment class filter")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Emit JSON results")
    args = parser.parse_args(argv)

    catalog_path = args.catalog.resolve()
    if not catalog_path.is_file():
        print(f"error: missing catalog index: {catalog_path}", file=sys.stderr)
        return 1

    payload = load_catalog_index(catalog_path)
    hits = search_catalog(
        payload=payload,
        query=args.query,
        role=args.role,
        color=args.color,
        garment_class=args.garment_class,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps([hit.to_dict() for hit in hits], indent=2))
    else:
        print(format_hits(hits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
