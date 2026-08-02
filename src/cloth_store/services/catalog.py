"""Read-only catalogue access for the storefront API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloth_store.catalog_catalog_index import load_catalog_index
from cloth_store.catalog_catalog_search import SearchHit, search_catalog
from cloth_store.catalog_paths import resolve_catalog_id

_UNKNOWN_VALUES = frozenset(
    {
        "not applicable",
        "none visible",
        "not discernible at this resolution",
        "unknown",
    }
)

_LABEL_FACETS: tuple[tuple[str, str], ...] = (
    ("colors", "color"),
    ("garment_class", "class"),
    ("material", "material"),
    ("pattern", "pattern"),
    ("silhouette_style", "silhouette"),
    ("sleeve_length", "sleeves"),
)

_GARMENT_DISPLAY_PHRASES: dict[str, str] = {
    "office_blouse": "Office Blouse",
    "blouse": "Blouse",
    "shirt": "Shirt",
    "t-shirt": "T-Shirt",
    "blazer": "Blazer",
    "waistcoat": "Waistcoat",
    "trousers": "Trousers",
    "pants": "Trousers",
    "skirt": "Skirt",
}

_TSHIRT_NECKLINE_MARKERS = ("v-neck", "v neckline", "crew neck", "round neck", "rounded neckline")

CATALOGUE_DESCRIPTION_PROMPT_PATH = Path("prompts/catalogue_description_system.md")
DESCRIPTION_MAX_WORDS = 35

_FORMAL_EDIT_FALLBACK = "A refined formal piece from the collection."
_FORMAL_TROUSER_FALLBACK = "straight-leg cut"

_SUPPORTED_TROUSER_FITS = frozenset({"straight", "slim", "relaxed", "regular", "wide"})

_PROHIBITED_PHRASES: tuple[str, ...] = (
    "elegant drape",
    "quiet luminosity",
    "evening poise",
    "office-ready polish",
    "office-ready",
    "refined visual interest",
    "poised elegance",
    "sharp formal line",
    "refined layering within the collection",
    "lends polished structure",
    "completes the tailored front",
    "front fly",
    "button-front fly",
    "placket",
    "luxurious",
    "timeless",
    "perfect for",
)


@dataclass(frozen=True, slots=True)
class DescriptionFacts:
    role: str
    garment_class: str | None
    color: str | None
    garment_noun: str
    material: str | None
    pattern: str | None
    sheen: str | None
    finish: str | None
    neckline: str | None
    closure: str | None
    silhouette: str | None
    subtype: str | None
    sleeve_length: str | None
    fit: str | None = None
    is_tshirt: bool = False


_JARGON_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("button-front fly", "button at the waist"),
    ("front fly", "button at the waist"),
    ("single-button front", "a single front button"),
    ("zip-and-button front closure", "a zip-and-button waist"),
    ("front zip closure", "a zip waist"),
    ("front placket", "the front"),
    ("button-front placket", "button through the front"),
)


def _normalize_facet_text(text: str) -> str:
    cleaned = text.strip().rstrip(".")
    if not cleaned:
        return cleaned
    replacements = (
        (" vertically aligned on center front", ""),
        (" visible", ""),
        (" implied", ""),
        (" at this resolution", ""),
        (" at waistband", ""),
        ("notched lapel neckline", "notched lapel"),
        ("no sleeves", "sleeveless"),
        ("full sleeves", "long sleeves"),
        (" v-neckline", " V-neck"),
        (" v- neckline", " V-neck"),
        ("buttoned cuffs", "cuffed sleeves"),
        ("front placket", "front"),
        (" with structured drape", ""),
        (" with slight drape", ""),
        (" with slight stiffness", " with a crisp hand"),
    )
    for old, new in replacements:
        cleaned = cleaned.replace(old, new)
    return cleaned.strip()


def _condense_detail(text: str, *, max_words: int = 10) -> str:
    cleaned = _normalize_facet_text(text)
    if not cleaned:
        return cleaned
    cleaned = cleaned.replace(";", ",")
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    cleaned = parts[0] if len(parts) == 1 else ", ".join(parts[:2])
    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words])
    if cleaned and cleaned[0].isalpha():
        return cleaned[0].lower() + cleaned[1:]
    return cleaned


def _humanize_fabric(material: str) -> str:
    fabric = _condense_detail(material, max_words=8)
    fabric = fabric.replace("satin-like woven fabric", "a satin-like weave")
    fabric = fabric.replace("structured woven fabric", "structured woven cloth")
    fabric = fabric.replace("smooth woven fabric", "smooth woven cloth")
    fabric = fabric.replace("woven fabric", "woven cloth")
    fabric = fabric.replace(
        "woven cloth with openwork detailing",
        "woven cloth with openwork detail",
    )
    return fabric


def _finalize_editorial_copy(text: str) -> str:
    polished = _polish_storefront_text(text)
    for old, new in _JARGON_REPLACEMENTS:
        polished = polished.replace(old, new)
        polished = polished.replace(old.title(), new[0].upper() + new[1:] if new else new)
    for phrase in _PROHIBITED_PHRASES:
        if phrase in polished.lower():
            polished = polished.replace(phrase, "")
            polished = polished.replace(phrase.title(), "")
    while "  " in polished:
        polished = polished.replace("  ", " ")
    polished = polished.replace(" ,", ",").replace(",,", ",").replace(" .", ".")
    polished = polished.replace(",.", ".").replace("..", ".")
    return polished.strip()


def _trim_word_count(text: str, max_words: int = DESCRIPTION_MAX_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = " ".join(words[:max_words]).rstrip(",;")
    if not trimmed.endswith("."):
        trimmed += "."
    return trimmed


def _capitalize_sentence(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


def _with_article(color: str) -> str:
    lower = color.lower().strip()
    if lower.startswith(("a ", "an ")):
        return lower
    first = lower.split()[0]
    vowel_colors = {"off-white", "orange", "olive", "ivory", "ecru"}
    article = "an" if first in vowel_colors or lower[0] in "aeiou" else "a"
    return f"{article} {lower}"


def _shopper_sleeves(
    neckline: str | None,
    sleeve_length: str | None,
) -> str | None:
    if neckline:
        lowered = neckline.lower()
        if "sleeveless" in lowered or "no sleeves" in lowered:
            return "sleeveless"
        if "short sleeve" in lowered:
            return "short sleeves"
        if "long sleeve" in lowered or "full sleeve" in lowered:
            return "long sleeves"
    if sleeve_length:
        normalized = sleeve_length.lower()
        if normalized in {"full", "long"}:
            return "long sleeves"
        if normalized == "short":
            return "short sleeves"
    return None


def _shopper_neckline_detail(
    neckline: str | None,
    garment_class: str | None,
    *,
    is_tshirt: bool,
) -> str | None:
    if not neckline:
        return None
    lowered = neckline.lower()
    if is_tshirt and "v-neck" in lowered:
        return "a V-neck"
    if garment_class == "blazer" and "lapel" in lowered:
        return "a notched lapel"
    if garment_class == "waistcoat" and "v-neck" in lowered:
        return "a deep V-neck"
    if "pointed collar" in lowered or (
        garment_class in {"office_blouse", "blouse", "shirt"} and "collar" in lowered
    ):
        return "a pointed collar"
    if "rounded neckline" in lowered or "round neck" in lowered:
        return "a rounded neckline"
    if "sweetheart" in lowered:
        return "a sweetheart neckline"
    if "ruffled collar" in lowered:
        return "a ruffled collar"
    if "halter" in lowered:
        return "a halter neckline"
    if "mock neck" in lowered or "high mock" in lowered:
        return "a high mock neckline"
    if "v-neck" in lowered or "v neck" in lowered:
        return "a V-neck"
    if "keyhole" in lowered:
        return "a keyhole neckline"
    return None


def _shopper_pattern(pattern: str | None) -> str | None:
    if not pattern:
        return None
    lowered = pattern.lower()
    if lowered in {"solid", "none visible"} or lowered.startswith("solid with"):
        return None
    if "ribbing" in lowered:
        return None
    mapping = {
        "floral print": "a floral print",
        "print": "an all-over print",
        "checkered": "a checkered pattern",
        "striped": "stripes",
        "plaid": "a plaid pattern",
        "embroidery and eyelet perforations": "openwork embroidery",
        "eyelet perforation pattern with embroidered trim": "eyelet embroidery",
    }
    if lowered in mapping:
        return mapping[lowered]
    condensed = _condense_detail(pattern, max_words=5)
    if not condensed:
        return None
    if condensed[0].isalpha() and condensed.split()[0] not in {"a", "an"}:
        return f"a {condensed} pattern"
    return condensed


def _shopper_texture(
    finish: str | None,
    pattern: str | None,
    material: str | None,
) -> str | None:
    if material and "ribbing" in material.lower():
        return None
    if finish and "ribbing" in finish.lower():
        return _condense_detail(finish, max_words=4)
    if pattern and "ribbing" in pattern.lower():
        detail = pattern.removeprefix("solid with ").strip()
        return _condense_detail(detail, max_words=5)
    return None


def _shopper_sheen(sheen: str | None) -> str | None:
    if not sheen:
        return None
    lowered = sheen.lower()
    if lowered in {"matte", "low sheen"}:
        return None
    if "satin" in lowered:
        return "a soft satin sheen"
    return None


def _shopper_top_closure(closure: str | None, garment_class: str | None) -> str | None:
    if not closure:
        return None
    lowered = closure.lower()
    if garment_class == "blazer":
        if "single" in lowered and "button" in lowered:
            return "closes with a single front button"
        if "two-button" in lowered or "two button" in lowered:
            return "closes with two front buttons"
        if "button" in lowered:
            return "closes with front buttons"
    if garment_class == "waistcoat" and "button" in lowered:
        if "three" in lowered:
            return "closes with three front buttons"
        return "closes with front buttons"
    if garment_class in {"office_blouse", "blouse", "shirt"} and "button" in lowered:
        return "buttons through the front"
    if "button" in lowered:
        return "closes with front buttons"
    return None


def _shopper_waist_closure(closure: str | None) -> str | None:
    if not closure:
        return None
    lowered = closure.lower()
    if "not visible" in lowered or "mechanism not" in lowered or "not clearly visible" in lowered:
        return "have belt loops at the waist"
    if "no visible closure" in lowered:
        return None
    if "zipper" in lowered and "button" in lowered:
        return "fasten with a zip-and-button waist"
    if "zipper" in lowered or "zip" in lowered:
        return "fasten with a zip waist"
    if "button" in lowered or "fly" in lowered:
        return "button at the waist"
    if "belt loop" in lowered:
        return "have belt loops at the waist"
    return None


def _normalize_trouser_fit(fit: str | None) -> str | None:
    if not fit:
        return None
    normalized = fit.strip().lower()
    if normalized not in _SUPPORTED_TROUSER_FITS:
        return None
    return normalized


def _trouser_garment_noun(*, fit: str | None, silhouette: str | None) -> str:
    normalized_fit = _normalize_trouser_fit(fit)
    if normalized_fit:
        return f"{normalized_fit}-fit trousers"
    if silhouette:
        condensed = _condense_detail(silhouette, max_words=4)
        if condensed:
            return condensed
    return "trousers"


def _trouser_noun_has_leg_shape(garment_noun: str) -> bool:
    lowered = garment_noun.lower()
    markers = (
        "straight-leg",
        "straight leg",
        "straight-fit",
        "slim-fit",
        "relaxed-fit",
        "regular-fit",
        "wide-fit",
        "-fit trousers",
    )
    return any(marker in lowered for marker in markers)


def _extract_description_facts(item: dict[str, Any]) -> DescriptionFacts:
    garment_class = _resolve_storefront_garment_class(item)
    subtype = _optional_str(item.get("garment_subtype"))
    role = str(item.get("role", ""))
    is_tshirt = garment_class == "t-shirt"

    if _is_trouser_item(item):
        silhouette = _facet_value(item, "silhouette_style")
        fit = _facet_value(item, "fit")
        garment_noun = _trouser_garment_noun(fit=fit, silhouette=silhouette)
    elif garment_class == "skirt" and subtype:
        garment_noun = f"{subtype.lower()} skirt"
    else:
        garment_noun = _garment_noun_for_copy(
            garment_class=garment_class,
            subtype=subtype,
            sleeve_length=_facet_value(item, "sleeve_length"),
            role=role,
        )

    return DescriptionFacts(
        role=role,
        garment_class=garment_class,
        color=_facet_value(item, "colors"),
        garment_noun=garment_noun,
        material=_facet_value(item, "material"),
        pattern=_facet_value(item, "pattern"),
        sheen=_facet_value(item, "sheen"),
        finish=_facet_value(item, "finish"),
        neckline=_facet_value(item, "neckline_collar"),
        closure=_facet_value(item, "closure"),
        silhouette=_facet_value(item, "silhouette_style"),
        subtype=subtype,
        sleeve_length=_facet_value(item, "sleeve_length"),
        fit=_normalize_trouser_fit(_facet_value(item, "fit")),
        is_tshirt=is_tshirt,
    )


def _trouser_subject(facts: DescriptionFacts) -> str:
    if facts.color:
        return f"{facts.color.lower()} {facts.garment_noun}"
    return facts.garment_noun


def _compose_trouser_description(facts: DescriptionFacts) -> str:
    subject = _trouser_subject(facts).capitalize()
    fabric = _humanize_fabric(facts.material) if facts.material else None
    texture = _shopper_texture(facts.finish, facts.pattern, facts.material)
    if fabric and texture and texture.lower() in fabric.lower():
        texture = None
    sheen = _shopper_sheen(facts.sheen)
    waist = _shopper_waist_closure(facts.closure)

    if fabric and texture and waist:
        text = f"{subject} in {fabric} with {texture} {waist}."
    elif fabric and sheen and waist:
        if "button" in waist:
            text = f"{subject} in {fabric} carry {sheen} and button at the waist."
        else:
            text = f"{subject} in {fabric} carry {sheen} and {waist}."
    elif fabric and waist:
        if waist.startswith("button"):
            text = f"{subject} in {fabric} and {waist}."
        else:
            text = f"{subject} in {fabric} {waist}."
    elif fabric and texture:
        text = f"{subject} in {fabric} with {texture}."
    elif fabric and sheen:
        text = f"{subject} in {fabric} carry {sheen}."
    elif texture and waist:
        text = f"{subject} with {texture} {waist}."
    elif fabric:
        text = f"{subject} in {fabric}."
    elif texture:
        text = f"{subject} with {texture}."
    elif sheen:
        text = f"{subject} with {sheen}."
    elif waist:
        text = f"{subject} {waist}."
    elif _trouser_noun_has_leg_shape(facts.garment_noun):
        text = f"{subject}."
    else:
        text = f"{subject} with a clean {_FORMAL_TROUSER_FALLBACK}."

    return _capitalize_sentence(text)


def _compose_blazer_description(facts: DescriptionFacts) -> str:
    color = _with_article(facts.color or "tailored")
    sleeves = _shopper_sleeves(facts.neckline, facts.sleeve_length)
    neckline = _shopper_neckline_detail(facts.neckline, facts.garment_class, is_tshirt=False)
    closure = _shopper_top_closure(facts.closure, facts.garment_class)
    fabric = _humanize_fabric(facts.material) if facts.material else None
    pattern = _shopper_pattern(facts.pattern)

    lead = f"{color.capitalize()} blazer"
    if fabric and pattern:
        detail = f" in {fabric} with {pattern}"
    elif fabric:
        detail = f" in {fabric}"
    elif pattern:
        detail = f" with {pattern}"
    else:
        detail = ""

    body_parts: list[str] = []
    if sleeves:
        body_parts.append(sleeves)
    if neckline:
        body_parts.append(neckline)

    if body_parts and closure:
        joined = " and ".join(body_parts)
        text = f"{lead}{detail} with {joined} {closure}."
    elif body_parts:
        joined = " and ".join(body_parts)
        text = f"{lead}{detail} with {joined}."
    elif closure:
        text = f"{lead}{detail} {closure}."
    else:
        text = f"{lead}{detail}."

    return _capitalize_sentence(text)


def _compose_tshirt_description(facts: DescriptionFacts) -> str:
    color = _with_article(facts.color or "black")
    neckline = _shopper_neckline_detail(facts.neckline, facts.garment_class, is_tshirt=True)
    sleeves = _shopper_sleeves(facts.neckline, facts.sleeve_length)

    if sleeves == "long sleeves" and neckline:
        text = (
            f"{color.capitalize()} long-sleeve T-shirt with {neckline} "
            f"is cut for layering under tailored jackets and waistcoats."
        )
    elif neckline:
        text = f"{color.capitalize()} T-shirt with {neckline} works as a refined layering piece."
    else:
        text = (
            f"{color.capitalize()} T-shirt works as a refined layering piece "
            f"beneath tailored pieces."
        )

    return _capitalize_sentence(text)


def _compose_waistcoat_description(facts: DescriptionFacts) -> str:
    color = _with_article(facts.color or "tailored")
    neckline = _shopper_neckline_detail(facts.neckline, facts.garment_class, is_tshirt=False)
    closure = _shopper_top_closure(facts.closure, facts.garment_class)

    if neckline and closure:
        text = f"{color.capitalize()} waistcoat with {neckline} and a sleeveless cut {closure}."
    elif neckline:
        text = f"{color.capitalize()} waistcoat with {neckline} and a sleeveless cut."
    else:
        text = f"{color.capitalize()} waistcoat with a sleeveless tailored cut."

    return _capitalize_sentence(text)


def _compose_skirt_description(facts: DescriptionFacts) -> str:
    color = _with_article(facts.color or "tailored")
    fabric = _humanize_fabric(facts.material) if facts.material else None
    subtype = facts.subtype or "pencil"

    if fabric:
        text = f"{color.capitalize()} {subtype} skirt in {fabric}."
    else:
        text = f"{color.capitalize()} {subtype} skirt with a clean fitted line."

    return _capitalize_sentence(text)


def _compose_blouse_description(facts: DescriptionFacts) -> str:
    color = _with_article(facts.color or "soft")
    garment = facts.garment_noun
    fabric = _humanize_fabric(facts.material) if facts.material else None
    pattern = _shopper_pattern(facts.pattern)
    if fabric and pattern and "eyelet" in fabric.lower() and "eyelet" in pattern.lower():
        pattern = None
    sheen = _shopper_sheen(facts.sheen)
    sleeves = _shopper_sleeves(facts.neckline, facts.sleeve_length)
    neckline = _shopper_neckline_detail(
        facts.neckline,
        facts.garment_class,
        is_tshirt=facts.is_tshirt,
    )
    closure = _shopper_top_closure(facts.closure, facts.garment_class)

    lead = f"{color.capitalize()} {garment}"
    intro = ""
    if fabric and pattern:
        intro = f" in {fabric} with {pattern}"
    elif fabric:
        intro = f" in {fabric}"
    elif pattern:
        intro = f" with {pattern}"

    if sleeves == "sleeveless" and facts.neckline and "halter" in facts.neckline.lower():
        text = f"{lead}{intro} has a sleeveless halter neckline."
    elif sleeves == "sleeveless" and neckline and closure:
        text = f"{lead}{intro} is sleeveless with {neckline} and {closure}."
    elif sleeves == "sleeveless" and neckline:
        text = f"{lead}{intro} is sleeveless with {neckline}."
    elif sleeves and neckline and closure:
        text = f"{lead}{intro} pairs {sleeves} with {neckline} and {closure}."
    elif sleeves and neckline:
        text = f"{lead}{intro} pairs {sleeves} with {neckline}."
    elif sleeves and closure:
        text = f"{lead}{intro} has {sleeves} and {closure}."
    elif neckline and closure:
        text = f"{lead}{intro} features {neckline} and {closure}."
    elif sleeves:
        text = f"{lead}{intro} is cut with {sleeves}."
    elif neckline:
        text = f"{lead}{intro} features {neckline}."
    elif closure:
        text = f"{lead}{intro} {closure}."
    elif sheen:
        text = f"{lead}{intro} finished with {sheen}."
    elif intro:
        text = f"{lead}{intro}."
    else:
        text = f"{lead} with a clean polished line."

    return _capitalize_sentence(text)


def _compose_fluent_description(facts: DescriptionFacts) -> str:
    if facts.garment_class in {"trousers", "pants"} or facts.garment_noun.endswith("trousers"):
        return _compose_trouser_description(facts)
    if facts.garment_class == "blazer":
        return _compose_blazer_description(facts)
    if facts.is_tshirt:
        return _compose_tshirt_description(facts)
    if facts.garment_class == "waistcoat":
        return _compose_waistcoat_description(facts)
    if facts.garment_class == "skirt" or "skirt" in facts.garment_noun:
        return _compose_skirt_description(facts)
    return _compose_blouse_description(facts)


def _is_trouser_item(item: dict[str, Any]) -> bool:
    garment_class = (_resolve_storefront_garment_class(item) or "").lower()
    return garment_class in {"trousers", "pants"}


def build_item_description(item: dict[str, Any]) -> str:
    """Compose fluent storefront copy aligned with prompts/catalogue_description_system.md."""
    facts = _extract_description_facts(item)
    composed = _compose_fluent_description(facts)
    return _finalize_editorial_copy(_trim_word_count(composed))


@dataclass(frozen=True, slots=True)
class CatalogLabel:
    kind: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True, slots=True)
class CatalogItemView:
    catalog_id: str
    display_name: str
    role: str
    fixture: str
    description: str
    labels: tuple[CatalogLabel, ...]
    image_url: str
    garment_class: str | None
    tags: tuple[str, ...]
    search_score: int | None = None
    matched_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "catalog_id": self.catalog_id,
            "display_name": self.display_name,
            "role": self.role,
            "fixture": self.fixture,
            "description": self.description,
            "labels": [label.to_dict() for label in self.labels],
            "image_url": self.image_url,
            "garment_class": self.garment_class,
            "tags": list(self.tags),
        }
        if self.search_score is not None:
            payload["search_score"] = self.search_score
        if self.matched_fields:
            payload["matched_fields"] = list(self.matched_fields)
        return payload


@dataclass(frozen=True, slots=True)
class CatalogBrowseResult:
    query: str
    role: str | None
    color: str | None
    garment_class: str | None
    total: int
    items: tuple[CatalogItemView, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "filters": {
                "role": self.role,
                "color": self.color,
                "garment_class": self.garment_class,
            },
            "total": self.total,
            "items": [item.to_dict() for item in self.items],
        }


class CatalogUnavailableError(RuntimeError):
    """Raised when the processed catalogue index cannot be loaded."""


class CatalogService:
    """Loads ``final_catalog/catalog.json`` and exposes browse/search views."""

    def __init__(
        self,
        *,
        catalog_json_path: Path,
        final_catalog_root: Path,
        assets_url_prefix: str = "/catalog-assets",
    ) -> None:
        self._catalog_json_path = catalog_json_path.resolve()
        self._final_catalog_root = final_catalog_root.resolve()
        self._assets_url_prefix = assets_url_prefix.rstrip("/")
        self._payload: dict[str, Any] | None = None
        self._items_by_id: dict[str, dict[str, Any]] = {}
        self._load_error: str | None = None
        self.reload()

    @property
    def is_available(self) -> bool:
        return self._payload is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def summary(self) -> dict[str, Any]:
        self._require_payload()
        return dict(self._payload["summary"])

    def reload(self) -> None:
        self._payload = None
        self._items_by_id = {}
        self._load_error = None

        if not self._catalog_json_path.is_file():
            self._load_error = f"missing catalog index: {self._catalog_json_path}"
            return

        try:
            payload = load_catalog_index(self._catalog_json_path)
        except (OSError, ValueError) as error:
            self._load_error = str(error)
            return

        self._payload = payload
        self._items_by_id = {
            str(item["catalog_id"]): item
            for item in payload.get("items", [])
            if isinstance(item, dict)
        }

    def browse(
        self,
        *,
        query: str = "",
        role: str | None = None,
        color: str | None = None,
        garment_class: str | None = None,
        limit: int | None = None,
    ) -> CatalogBrowseResult:
        payload = self._require_payload()
        hits = search_catalog(
            payload=payload,
            query=query,
            role=role,
            color=color,
            garment_class=garment_class,
            limit=limit,
        )
        items = tuple(self._view_from_hit(hit) for hit in hits)
        return CatalogBrowseResult(
            query=query,
            role=role,
            color=color,
            garment_class=garment_class,
            total=len(items),
            items=items,
        )

    def get_item(self, catalog_id: str) -> CatalogItemView | None:
        self._require_payload()
        item = self._items_by_id.get(resolve_catalog_id(catalog_id))
        if item is None:
            return None
        return self._view_from_item(item)

    def get_raw_item(self, catalog_id: str) -> dict[str, Any] | None:
        self._require_payload()
        item = self._items_by_id.get(resolve_catalog_id(catalog_id))
        if item is None:
            return None
        return item

    def iter_raw_items(self) -> tuple[dict[str, Any], ...]:
        payload = self._require_payload()
        return tuple(item for item in payload.get("items", []) if isinstance(item, dict))

    def _require_payload(self) -> dict[str, Any]:
        if self._payload is None:
            message = self._load_error or "catalogue unavailable"
            raise CatalogUnavailableError(message)
        return self._payload

    def _view_from_hit(self, hit: SearchHit) -> CatalogItemView:
        item = self._items_by_id[hit.catalog_id]
        view = self._view_from_item(item)
        return CatalogItemView(
            catalog_id=view.catalog_id,
            display_name=view.display_name,
            role=view.role,
            fixture=view.fixture,
            description=view.description,
            labels=view.labels,
            image_url=view.image_url,
            garment_class=view.garment_class,
            tags=view.tags,
            search_score=hit.score,
            matched_fields=hit.matched_fields,
        )

    def _view_from_item(self, item: dict[str, Any]) -> CatalogItemView:
        product_name = build_product_name(item)
        return CatalogItemView(
            catalog_id=str(item["catalog_id"]),
            display_name=product_name,
            role=str(item.get("role", "")),
            fixture=str(item.get("fixture", "")),
            description=build_item_description(item),
            labels=tuple(build_item_labels(item)),
            image_url=self._image_url(item),
            garment_class=_optional_str(item.get("garment_class_normalized")),
            tags=tuple(str(tag) for tag in item.get("tags", [])),
        )

    def _image_url(self, item: dict[str, Any]) -> str:
        rel_path = item.get("images", {}).get("output_512", {}).get("path")
        if not isinstance(rel_path, str) or not rel_path:
            raise CatalogUnavailableError(
                f"{item.get('catalog_id')} missing output_512 image metadata"
            )
        return f"{self._assets_url_prefix}/{rel_path.replace(chr(92), '/')}"


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _facet_value(item: dict[str, Any], field_name: str) -> str | None:
    facet = item.get("facets", {}).get(field_name, {})
    if not isinstance(facet, dict):
        return None
    value = facet.get("value")
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in _UNKNOWN_VALUES:
        return None
    return cleaned


def _title_phrase(text: str) -> str:
    parts: list[str] = []
    for token in text.replace("_", " ").split():
        lower = token.lower()
        if lower == "off-white":
            parts.append("Off-White")
        elif lower in {"t-shirt", "tshirt"}:
            parts.append("T-Shirt")
        else:
            parts.append(token.capitalize())
    return " ".join(parts)


def _format_word(word: str) -> str:
    lower = word.lower()
    if lower in {"t-shirt", "tshirt"}:
        return "T-Shirt"
    if lower == "off-white":
        return "Off-White"
    return word.capitalize()


def _storefront_sleeveless_top_phrase(garment_class: str | None) -> str | None:
    if not garment_class:
        return None
    normalized = garment_class.lower().replace(" ", "_")
    if normalized in {"tank_top", "tank"}:
        return "Tank Top"
    if normalized in {"blouse", "shirt", "office_blouse"}:
        return "Sleeveless Top"
    return None


def _garment_phrase_for_display(
    garment_class: str | None,
    subtype: str | None,
    *,
    sleeve_length: str | None = None,
    role: str | None = None,
) -> str:
    if role == "top" and sleeve_length == "sleeveless":
        sleeveless_phrase = _storefront_sleeveless_top_phrase(garment_class)
        if sleeveless_phrase:
            return sleeveless_phrase
    if garment_class == "skirt" and subtype:
        return f"{_title_phrase(subtype)} Skirt"
    if garment_class:
        key = garment_class.lower().replace(" ", "_")
        if key in _GARMENT_DISPLAY_PHRASES:
            return _GARMENT_DISPLAY_PHRASES[key]
        normalized = garment_class.lower().replace("_", " ")
        return " ".join(_format_word(part) for part in normalized.split())
    return "Piece"


def _metadata_indicates_tshirt(item: dict[str, Any]) -> bool:
    """Detect pullover tee silhouettes mislabeled as blouses in source metadata."""
    garment_class = (_facet_value(item, "garment_class") or "").lower()
    if garment_class not in {"blouse", "shirt"}:
        return False
    if _facet_value(item, "closure"):
        return False

    neckline = (_facet_value(item, "neckline_collar") or "").lower()
    if not neckline:
        return False
    if any(marker in neckline for marker in ("collar", "button", "placket", "lapel")) and (
        "v-neck" not in neckline and "rounded neckline" not in neckline
    ):
        return False
    if "pointed collar" in neckline or "structured collar" in neckline:
        return False
    if "halter" in neckline or "sleeveless" in neckline:
        return False

    return any(marker in neckline for marker in _TSHIRT_NECKLINE_MARKERS)


def _resolve_storefront_garment_class(item: dict[str, Any]) -> str | None:
    garment_class = _facet_value(item, "garment_class") or _optional_str(
        item.get("garment_class_normalized")
    )
    catalog_id = str(item.get("catalog_id", ""))
    if catalog_id == "outfit_11_top" and _metadata_indicates_tshirt(item):
        return "t-shirt"
    return garment_class


def build_product_name(item: dict[str, Any]) -> str:
    """Format a polished, human-facing product name for storefront cards."""
    color = _facet_value(item, "colors")
    garment_class = _resolve_storefront_garment_class(item)
    subtype = _optional_str(item.get("garment_subtype"))
    garment_phrase = _garment_phrase_for_display(
        garment_class,
        subtype,
        sleeve_length=_facet_value(item, "sleeve_length"),
        role=_optional_str(item.get("role")),
    )

    if color:
        return f"{_title_phrase(color)} {garment_phrase}"

    raw_name = str(item.get("display_name", "")).strip()
    if raw_name:
        polished = _title_phrase(raw_name.replace("_", " "))
        if garment_phrase.lower() not in polished.lower():
            return f"{polished} {garment_phrase}".strip()
        return polished
    return garment_phrase


def _garment_noun_for_copy(
    *,
    garment_class: str | None,
    subtype: str | None,
    sleeve_length: str | None = None,
    role: str | None = None,
) -> str:
    if garment_class == "t-shirt":
        return "T-shirt"
    return _garment_phrase_for_display(
        garment_class,
        subtype,
        sleeve_length=sleeve_length,
        role=role,
    ).lower()


def _polish_storefront_text(text: str) -> str:
    """Ensure visible storefront copy never exposes slug-like identifiers."""
    polished = text.replace("_", " ")
    for slug, display in _GARMENT_DISPLAY_PHRASES.items():
        polished = polished.replace(slug, display.lower())
    while "  " in polished:
        polished = polished.replace("  ", " ")
    return polished.strip()


def _opening_phrase(
    *,
    color: str | None,
    garment: str,
) -> str:
    garment_lower = garment.lower()
    if garment_lower.endswith(("trousers", "pants")) or garment_lower in {"trousers", "pants"}:
        if color:
            return f"{color.lower()} {garment_lower}"
        return garment_lower.title()
    if garment_lower == "t-shirt":
        if color:
            return f"A {color.lower()} T-shirt"
        return "A T-shirt"
    if color:
        return f"A {color.lower()} {garment_lower}"
    return f"A {garment_lower}"


def _capitalize_opening(text: str) -> str:
    if not text:
        return text
    if text.lower().startswith("a "):
        return f"A {text[2:]}"
    return text[0].upper() + text[1:]


def build_item_labels(item: dict[str, Any]) -> list[CatalogLabel]:
    labels: list[CatalogLabel] = []
    role = _optional_str(item.get("role"))
    if role:
        labels.append(CatalogLabel(kind="role", value=role.title()))

    seen_values: set[str] = set()
    for field_name, kind in _LABEL_FACETS:
        value = _facet_value(item, field_name)
        if value is None:
            continue
        normalized = value.casefold()
        if normalized in seen_values:
            continue
        seen_values.add(normalized)
        labels.append(CatalogLabel(kind=kind, value=value))

    template_id = item.get("template", {}).get("template_id")
    if isinstance(template_id, str) and template_id.strip():
        labels.append(CatalogLabel(kind="template", value=template_id.replace("_", " ")))

    for tag in item.get("tags", []):
        if not isinstance(tag, str):
            continue
        normalized = tag.casefold()
        if normalized in seen_values or normalized in {role.casefold() if role else ""}:
            continue
        if normalized.startswith("outfit_"):
            continue
        seen_values.add(normalized)
        labels.append(CatalogLabel(kind="tag", value=tag))
        if len(labels) >= 8:
            break

    return labels
