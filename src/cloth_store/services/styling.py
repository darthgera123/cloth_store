"""Resolve catalogue garments to styled selfies and same-fixture partners."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cloth_store.catalog_paths import (
    DEFAULT_SOURCE_PHOTO_DIR,
    fixture_number,
    resolve_fixture_source_path,
)
from cloth_store.services.catalog import CatalogItemView, build_product_name

if TYPE_CHECKING:
    from cloth_store.services.catalog import CatalogService


@dataclass(frozen=True, slots=True)
class StylingSelfieRef:
    fixture: str
    image_url: str | None
    available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "image_url": self.image_url,
            "available": self.available,
        }


@dataclass(frozen=True, slots=True)
class StylingPartnerRef:
    catalog_id: str
    display_name: str
    role: str
    fixture: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "display_name": self.display_name,
            "role": self.role,
            "fixture": self.fixture,
        }


@dataclass(frozen=True, slots=True)
class StylingAssociation:
    fixture: str
    advice_title: str
    advice_text: str
    caption: str
    selfie: StylingSelfieRef
    partners: tuple[StylingPartnerRef, ...]
    catalog_items: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "advice_title": self.advice_title,
            "advice_text": self.advice_text,
            "caption": self.caption,
            "selfie": self.selfie.to_dict(),
            "partners": [partner.to_dict() for partner in self.partners],
            "catalog_items": list(self.catalog_items),
        }


@dataclass(frozen=True, slots=True)
class CatalogStylingView:
    catalog_id: str
    display_name: str
    role: str
    fixture: str
    description: str
    garment_id: str | None
    observation_ids: tuple[str, ...]
    associations: tuple[StylingAssociation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "display_name": self.display_name,
            "role": self.role,
            "fixture": self.fixture,
            "description": self.description,
            "garment_id": self.garment_id,
            "observation_ids": list(self.observation_ids),
            "associations": [association.to_dict() for association in self.associations],
        }


@dataclass(frozen=True, slots=True)
class FixtureStylingView:
    fixture: str
    selfie: StylingSelfieRef
    catalog_items: tuple[str, ...]
    associations: tuple[StylingAssociation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "selfie": self.selfie.to_dict(),
            "catalog_items": list(self.catalog_items),
            "associations": [association.to_dict() for association in self.associations],
        }


@dataclass(frozen=True, slots=True)
class OutfitGarmentRef:
    catalog_id: str
    display_name: str
    description: str
    role: str
    image_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "display_name": self.display_name,
            "description": self.description,
            "role": self.role,
            "image_url": self.image_url,
        }


@dataclass(frozen=True, slots=True)
class OutfitCandidateView:
    fixture: str
    selfie: StylingSelfieRef
    top: OutfitGarmentRef
    bottom: OutfitGarmentRef
    advice_title: str
    advice_text: str
    caption: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "selfie": self.selfie.to_dict(),
            "top": self.top.to_dict(),
            "bottom": self.bottom.to_dict(),
            "advice_title": self.advice_title,
            "advice_text": self.advice_text,
            "caption": self.caption,
        }


@dataclass(frozen=True, slots=True)
class LuckyPairView:
    top: OutfitGarmentRef
    bottom: OutfitGarmentRef
    summary: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "top": self.top.to_dict(),
            "bottom": self.bottom.to_dict(),
            "summary": self.summary,
            "note": self.note,
        }


LUCKY_PAIR_NOTE = (
    "This top and bottom have not been photographed together. "
    "Explore the pairing from catalogue views only."
)


FASHION_ADVICE_TITLE = "Fashion Advice"

_VOWEL_ARTICLE_WORDS = frozenset({"off-white", "orange", "olive", "ivory", "ecru"})
_PLURAL_GARMENT_TOKENS = frozenset({"trousers", "pants"})


def _normalize_garment_phrase(text: str) -> str:
    normalized = text.strip()
    for old, new in (("waisctoat", "waistcoat"), ("Waisctoat", "Waistcoat")):
        normalized = normalized.replace(old, new)
    return normalized


def _starts_with_vowel_sound(phrase: str) -> bool:
    lower = phrase.lower().strip()
    if not lower:
        return False
    first = lower.split()[0]
    if first in _VOWEL_ARTICLE_WORDS:
        return True
    return first[0] in "aeiou"


def _needs_indefinite_article(display_name: str) -> bool:
    lowered = display_name.lower().strip()
    words = lowered.split()
    if not words:
        return False
    if words[-1] in _PLURAL_GARMENT_TOKENS:
        return False
    return "trousers" not in lowered and " pants" not in f" {lowered} "


def partner_advice_phrase(display_name: str) -> str:
    cleaned = _normalize_garment_phrase(display_name)
    lowered = cleaned.lower().strip()
    if lowered.startswith(("a ", "an ")):
        return lowered
    if _needs_indefinite_article(cleaned):
        article = "an" if _starts_with_vowel_sound(lowered) else "a"
        return f"{article} {lowered}"
    return lowered


def join_partner_advice_phrases(names: tuple[str, ...]) -> str:
    phrases = tuple(partner_advice_phrase(name) for name in names)
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


def join_partner_names(names: tuple[str, ...]) -> str:
    """Lowercase partner names joined for display lists."""
    if not names:
        return ""
    lowered = tuple(_normalize_garment_phrase(name).lower() for name in names)
    if len(lowered) == 1:
        return lowered[0]
    if len(lowered) == 2:
        return f"{lowered[0]} and {lowered[1]}"
    return ", ".join(lowered[:-1]) + f", and {lowered[-1]}"


def build_styling_advice_text(
    focus_display_name: str,
    partner_display_names: tuple[str, ...],
) -> str:
    focus = _normalize_garment_phrase(focus_display_name)
    if not partner_display_names:
        return f"{focus}."
    partners = join_partner_advice_phrases(partner_display_names)
    return f"{focus} with {partners}."


def build_styling_advice(
    focus_display_name: str,
    partner_display_names: tuple[str, ...],
) -> tuple[str, str]:
    return (
        FASHION_ADVICE_TITLE,
        build_styling_advice_text(focus_display_name, partner_display_names),
    )


def build_styling_caption(focus_display_name: str, partner_display_names: tuple[str, ...]) -> str:
    """Backward-compatible body copy without the section heading prefix."""
    return build_styling_advice_text(focus_display_name, partner_display_names)


def try_resolve_fixture_selfie_path(
    fixture_id: str,
    *,
    repo_root: Path,
) -> Path | None:
    root = repo_root.resolve()
    try:
        return resolve_fixture_source_path(fixture_id, repo_root=root).resolve()
    except (FileNotFoundError, KeyError, ValueError):
        pass

    fallback = root / DEFAULT_SOURCE_PHOTO_DIR / f"{fixture_id}.jpeg"
    if fallback.is_file():
        return fallback.resolve()
    return None


def fixtures_for_item(item: dict[str, Any]) -> tuple[str, ...]:
    fixtures: list[str] = []
    seen: set[str] = set()

    for observation in item.get("source_observations", []):
        if not isinstance(observation, dict):
            continue
        fixture = observation.get("fixture")
        if isinstance(fixture, str) and fixture and fixture not in seen:
            fixtures.append(fixture)
            seen.add(fixture)

    if not fixtures:
        fixture = item.get("fixture")
        if isinstance(fixture, str) and fixture:
            fixtures.append(fixture)

    return tuple(sorted(fixtures, key=fixture_number))


class StylingResolver:
    """Map catalogue garments and fixtures to styled selfies without cross-outfit pairing."""

    def __init__(
        self,
        *,
        catalog_service: CatalogService,
        repo_root: Path,
        selfies_url_prefix: str = "/fixture-selfies",
    ) -> None:
        self._catalog_service = catalog_service
        self._repo_root = repo_root.resolve()
        self._selfies_url_prefix = selfies_url_prefix.rstrip("/")
        self._fixture_catalog_ids: dict[str, tuple[str, ...]] = {}
        self._rebuild_indices()

    def reload(self) -> None:
        self._rebuild_indices()

    def resolve_for_catalog_item(self, catalog_id: str) -> CatalogStylingView | None:
        item = self._catalog_service.get_raw_item(catalog_id)
        if item is None:
            return None

        view = self._catalog_service.get_item(catalog_id)
        if view is None:
            return None

        observation_ids = tuple(str(value) for value in item.get("observation_ids", [catalog_id]))
        garment_id = _optional_str(item.get("garment_id"))
        associations = self._associations_for_item(
            focus_item=item,
            focus_catalog_id=catalog_id,
            focus_display_name=view.display_name,
            focus_role=view.role,
        )

        return CatalogStylingView(
            catalog_id=view.catalog_id,
            display_name=view.display_name,
            role=view.role,
            fixture=view.fixture,
            description=view.description,
            garment_id=garment_id,
            observation_ids=observation_ids,
            associations=associations,
        )

    def resolve_for_fixture(self, fixture_id: str) -> FixtureStylingView:
        catalog_ids = self._fixture_catalog_ids.get(fixture_id, ())
        selfie = self._selfie_ref(fixture_id)
        associations: list[StylingAssociation] = []

        for catalog_id in catalog_ids:
            styling = self.resolve_for_catalog_item(catalog_id)
            if styling is None:
                continue
            for association in styling.associations:
                if association.fixture == fixture_id:
                    associations.append(association)

        return FixtureStylingView(
            fixture=fixture_id,
            selfie=selfie,
            catalog_items=catalog_ids,
            associations=tuple(associations),
        )

    def list_outfit_candidates(self) -> tuple[OutfitCandidateView, ...]:
        """Return same-fixture outfit pairs with selfie, top, and bottom catalogue items."""
        candidates: list[OutfitCandidateView] = []

        for fixture_id in sorted(self._fixture_catalog_ids, key=fixture_number):
            candidate = self._outfit_candidate_for_fixture(fixture_id)
            if candidate is not None:
                candidates.append(candidate)

        return tuple(candidates)

    def select_outfit_candidate(
        self,
        *,
        exclude_fixture: str | None = None,
        seed: int | None = None,
    ) -> OutfitCandidateView | None:
        """Pick one validated outfit candidate, optionally avoiding immediate repeats."""
        candidates = self.list_outfit_candidates()
        if not candidates:
            return None

        pool = candidates
        if exclude_fixture:
            filtered = tuple(
                candidate for candidate in candidates if candidate.fixture != exclude_fixture
            )
            if filtered:
                pool = filtered

        rng = random.Random(seed)
        return rng.choice(pool)

    def documented_top_bottom_pairs(self) -> frozenset[tuple[str, str]]:
        """Return every top/bottom pair linked by a same-fixture styling association."""
        pairs: set[tuple[str, str]] = set()

        for item in self._catalog_service.iter_raw_items():
            catalog_id = str(item["catalog_id"])
            view = self._catalog_service.get_item(catalog_id)
            if view is None or view.role != "top":
                continue

            associations = self._associations_for_item(
                focus_item=item,
                focus_catalog_id=catalog_id,
                focus_display_name=view.display_name,
                focus_role=view.role,
            )
            for association in associations:
                for partner in association.partners:
                    if partner.role == "bottom":
                        pairs.add((catalog_id, partner.catalog_id))

        return frozenset(pairs)

    def list_lucky_pair_candidates(self) -> tuple[LuckyPairView, ...]:
        """Return catalogue top/bottom pairs with no documented fixture selfie association."""
        documented = self.documented_top_bottom_pairs()
        tops: list[CatalogItemView] = []
        bottoms: list[CatalogItemView] = []

        for item in self._catalog_service.iter_raw_items():
            view = self._catalog_service.get_item(str(item["catalog_id"]))
            if view is None or not self._is_complete_outfit_garment(view):
                continue
            if view.role == "top":
                tops.append(view)
            elif view.role == "bottom":
                bottoms.append(view)

        candidates: list[LuckyPairView] = []
        for top_view in sorted(tops, key=lambda view: view.catalog_id):
            for bottom_view in sorted(bottoms, key=lambda view: view.catalog_id):
                if (top_view.catalog_id, bottom_view.catalog_id) in documented:
                    continue
                summary = build_styling_advice_text(
                    top_view.display_name,
                    (bottom_view.display_name,),
                )
                candidates.append(
                    LuckyPairView(
                        top=self._outfit_garment_ref(top_view),
                        bottom=self._outfit_garment_ref(bottom_view),
                        summary=summary,
                        note=LUCKY_PAIR_NOTE,
                    )
                )

        return tuple(candidates)

    def select_lucky_pair(
        self,
        *,
        exclude_top: str | None = None,
        exclude_bottom: str | None = None,
        seed: int | None = None,
    ) -> LuckyPairView | None:
        """Pick one undocumented top/bottom pair, optionally avoiding immediate repeats."""
        candidates = self.list_lucky_pair_candidates()
        if not candidates:
            return None

        pool = candidates
        if exclude_top and exclude_bottom:
            filtered = tuple(
                candidate
                for candidate in candidates
                if not (
                    candidate.top.catalog_id == exclude_top
                    and candidate.bottom.catalog_id == exclude_bottom
                )
            )
            if filtered:
                pool = filtered

        rng = random.Random(seed)
        return rng.choice(pool)

    def _outfit_candidate_for_fixture(self, fixture_id: str) -> OutfitCandidateView | None:
        selfie = self._selfie_ref(fixture_id)
        if not selfie.available or not selfie.image_url:
            return None

        catalog_ids = self._fixture_catalog_ids.get(fixture_id, ())
        tops: list[str] = []
        bottoms: list[str] = []

        for catalog_id in catalog_ids:
            view = self._catalog_service.get_item(catalog_id)
            if view is None:
                continue
            if view.role == "top":
                tops.append(catalog_id)
            elif view.role == "bottom":
                bottoms.append(catalog_id)

        if not tops or not bottoms:
            return None

        top_id = sorted(tops)[0]
        top_view = self._catalog_service.get_item(top_id)
        if top_view is None:
            return None

        partners = self._partner_refs(
            fixture_id=fixture_id,
            focus_catalog_id=top_id,
            focus_role="top",
        )
        bottom_partners = tuple(partner for partner in partners if partner.role == "bottom")
        if not bottom_partners:
            return None

        bottom_id = bottom_partners[0].catalog_id
        bottom_view = self._catalog_service.get_item(bottom_id)
        if bottom_view is None:
            return None

        advice_title, advice_text = build_styling_advice(
            top_view.display_name,
            (bottom_view.display_name,),
        )

        return OutfitCandidateView(
            fixture=fixture_id,
            selfie=selfie,
            top=self._outfit_garment_ref(top_view),
            bottom=self._outfit_garment_ref(bottom_view),
            advice_title=advice_title,
            advice_text=advice_text,
            caption=advice_text,
        )

    def _outfit_garment_ref(self, view: CatalogItemView) -> OutfitGarmentRef:
        return OutfitGarmentRef(
            catalog_id=view.catalog_id,
            display_name=view.display_name,
            description=view.description,
            role=view.role,
            image_url=view.image_url,
        )

    @staticmethod
    def _is_complete_outfit_garment(view: CatalogItemView) -> bool:
        if not view.display_name.strip() or not view.description.strip():
            return False
        if not view.image_url.endswith("/output.png"):
            return False
        return view.role in {"top", "bottom"}

    def _associations_for_item(
        self,
        *,
        focus_item: dict[str, Any],
        focus_catalog_id: str,
        focus_display_name: str,
        focus_role: str,
    ) -> tuple[StylingAssociation, ...]:
        associations: list[StylingAssociation] = []
        for fixture_id in fixtures_for_item(focus_item):
            partners = self._partner_refs(
                fixture_id=fixture_id,
                focus_catalog_id=focus_catalog_id,
                focus_role=focus_role,
            )
            partner_names = tuple(partner.display_name for partner in partners)
            advice_title, advice_text = build_styling_advice(focus_display_name, partner_names)
            caption = advice_text
            catalog_items = self._fixture_catalog_ids.get(fixture_id, ())
            associations.append(
                StylingAssociation(
                    fixture=fixture_id,
                    advice_title=advice_title,
                    advice_text=advice_text,
                    caption=caption,
                    selfie=self._selfie_ref(fixture_id),
                    partners=partners,
                    catalog_items=catalog_items,
                )
            )
        return tuple(associations)

    def _partner_refs(
        self,
        *,
        fixture_id: str,
        focus_catalog_id: str,
        focus_role: str,
    ) -> tuple[StylingPartnerRef, ...]:
        partners: list[StylingPartnerRef] = []
        seen: set[str] = set()

        for catalog_id in self._fixture_catalog_ids.get(fixture_id, ()):
            if catalog_id == focus_catalog_id:
                continue
            view = self._catalog_service.get_item(catalog_id)
            if view is None or view.role == focus_role:
                continue
            if catalog_id in seen:
                continue
            seen.add(catalog_id)
            partners.append(
                StylingPartnerRef(
                    catalog_id=view.catalog_id,
                    display_name=view.display_name,
                    role=view.role,
                    fixture=view.fixture,
                )
            )

        partners.sort(key=lambda partner: partner.role)
        return tuple(partners)

    def _selfie_ref(self, fixture_id: str) -> StylingSelfieRef:
        source_path = try_resolve_fixture_selfie_path(fixture_id, repo_root=self._repo_root)
        if source_path is None:
            return StylingSelfieRef(fixture=fixture_id, image_url=None, available=False)
        filename = source_path.name
        return StylingSelfieRef(
            fixture=fixture_id,
            image_url=f"{self._selfies_url_prefix}/{filename}",
            available=True,
        )

    def _rebuild_indices(self) -> None:
        self._fixture_catalog_ids = {}

        for item in self._catalog_service.iter_raw_items():
            catalog_id = str(item["catalog_id"])
            linked_fixtures = fixtures_for_item(item)
            for linked_fixture in linked_fixtures:
                existing = self._fixture_catalog_ids.get(linked_fixture, ())
                if catalog_id not in existing:
                    self._fixture_catalog_ids[linked_fixture] = existing + (catalog_id,)


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def display_name_for_item(item: dict[str, Any]) -> str:
    return build_product_name(item)
