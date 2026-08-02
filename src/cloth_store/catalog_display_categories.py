"""Storefront display categories derived from durable catalog garment metadata."""

from __future__ import annotations

DISPLAY_CATEGORY_ORDER: tuple[str, ...] = ("top", "blazer", "dress", "bottom")

# Structured classes that map to the Blazers storefront section.
# Suit jackets normalize to ``blazer`` upstream; waistcoats, shirts, and vests stay tops.
BLAZER_DISPLAY_GARMENT_CLASSES: frozenset[str] = frozenset({"blazer"})

DISPLAY_CATEGORY_LABELS: dict[str, str] = {
    "top": "Tops",
    "blazer": "Blazers",
    "dress": "Dresses",
    "bottom": "Bottoms",
}


def normalize_garment_class_token(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def is_blazer_garment_class(garment_class_normalized: str | None) -> bool:
    return normalize_garment_class_token(garment_class_normalized) in BLAZER_DISPLAY_GARMENT_CLASSES


def resolve_display_category(*, role: str, garment_class_normalized: str | None) -> str:
    """Map indexed catalog metadata to a storefront navigation section."""
    if role == "dress":
        return "dress"
    if role == "bottom":
        return "bottom"
    if role == "top":
        if is_blazer_garment_class(garment_class_normalized):
            return "blazer"
        return "top"
    return role
