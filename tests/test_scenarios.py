"""Ten scenario tests covering the highest-value system boundaries.

Per user policy the repository intentionally caps automated unit tests at
exactly ten collected cases. See README.md for rationale and tradeoffs.
"""

from __future__ import annotations

import io
import json
import re
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from cloth_store.catalog_catalog_index import (
    EXPECTED_ITEM_COUNT,
    EXPECTED_OBSERVATION_COUNT,
    build_catalog_index,
    serialize_catalog_index,
    validate_catalog_index,
    write_catalog_index,
)
from cloth_store.catalog_catalog_search import search_catalog
from cloth_store.catalog_cutouts import (
    CANVAS_SIZE as CUTOUT_CANVAS_SIZE,
)
from cloth_store.catalog_cutouts import (
    MARGIN_FRACTION as CUTOUT_MARGIN_FRACTION,
)
from cloth_store.catalog_cutouts import (
    WHITE_BACKGROUND,
    masked_rgb_cutout,
    render_catalog_cutout,
)
from cloth_store.catalog_derived_geometry import (
    GEOMETRY_CANDIDATE_NAMESPACE,
    IMAGE_ROLE_DERIVED_GEOMETRY,
    build_geometry_candidate_prompt,
    extract_neutral_geometry_silhouette,
    validate_derived_geometry_image,
    validate_derived_geometry_path,
    validate_geometry_source_path,
)
from cloth_store.catalog_exclusions import (
    EXPECTED_EXCLUDED_OBSERVATION_COUNT,
    default_exclusion_registry_path,
    load_exclusion_registry,
    validate_exclusion_registry,
)
from cloth_store.catalog_garment_identities import (
    EXPECTED_UNIQUE_GARMENT_COUNT,
    GarmentIdentityError,
    load_garment_identity_registry,
    validate_garment_identity_registry,
)
from cloth_store.catalog_output_contract import (
    CANONICAL_IMAGE_SIZE,
    CanonicalOutputPaths,
    estimate_canonical_cost_usd,
    sanitize_canonical_metadata,
    validate_canonical_outputs,
)
from cloth_store.catalog_paths import (
    plan1_fixture_ids,
    resolve_fixture_source_path,
    resolve_plan1_fixtures,
)
from cloth_store.catalog_pipeline import (
    PIPELINE_GENERATION_MODE,
    PRODUCTION_NAMESPACE,
    CatalogPipelineError,
    build_pipeline_plan,
    check_identity_alias_reuse_eligible,
    check_reference_promotion_eligible,
    run_pipeline_case,
    sanitize_pipeline_metadata,
)
from cloth_store.catalog_request_overrides import (
    DEFAULT_OUTFIT_6_OVERRIDE,
    USER_OVERRIDE_GARMENT_CLASS,
    build_user_corrected_prompt,
)
from cloth_store.catalog_template_selector import (
    GarmentAttributes,
    load_garment_attributes,
    normalize_garment_class,
    normalize_sleeve_length,
    select_template_from_attributes,
    validate_all_manifest_cases,
)
from cloth_store.catalog_templates import (
    CANVAS_SIZE,
    MARGIN_FRACTION,
    TEMPLATE_BY_ID,
    TEMPLATE_SPECS,
    pants_centerline_gap_rows,
    render_template_png,
    template_silhouette_width_metrics,
    visible_foreground_bounds,
)
from cloth_store.catalog_texture_qc import compare_texture_heuristic
from cloth_store.catalog_user_override import (
    build_user_override_clause,
    load_user_override,
)
from cloth_store.catalog_vlm_records import (
    build_vlm_attribute_clause,
    build_vlm_conditioned_prompt,
)
from cloth_store.gemini_catalog import (
    GEMINI_API_KEY_ENV,
    NANO_BANANA_2_MODEL_ID,
    AvailabilityCheckResult,
    GeminiCatalogConfig,
    GeminiCredentialsError,
    build_gemini_client,
    check_model_availability,
    credential_fallback_paths,
    redact_secret,
    resolve_gemini_api_key,
)
from cloth_store.gemini_catalog_generate import (
    CatalogGenerationError,
    build_generation_contents,
    build_run_metadata,
    extract_response_images,
    generation_request_settings,
    normalize_catalog_output,
    run_catalog_generation,
    sanitize_api_error,
    serialize_run_metadata,
    sha256_text,
)
from cloth_store.gemini_catalog_request import (
    ALLOWED_CUTOUT_PREFIX,
    ALLOWED_TEMPLATE_PREFIX,
    IMAGE_ROLE_GARMENT_DETAIL,
    IMAGE_ROLE_GARMENT_IDENTITY,
    IMAGE_ROLE_TEMPLATE_GEOMETRY,
    SMOKE_FIXTURE_ID,
    SMOKE_ROLE,
    SMOKE_TEMPLATE_ID,
    CatalogRequestArtifactError,
    build_catalog_generation_prompt,
    build_request_artifact,
    prompt_descriptor_leakage,
    serialize_request_artifact,
    sha256_file,
    template_prompt_policy,
    validate_prompt_constraints,
    validate_request_artifact,
    validate_source_provenance,
    write_request_artifact,
)
from cloth_store.sam_masks import (
    normalized_xyxy_to_pixel_box,
    normalized_xyxy_to_pixel_crop,
    original_box_to_crop_prompt,
    pad_normalized_box,
    place_crop_mask_in_full_image,
)
from cloth_store.selfie_final_packaging import (
    build_batched_contact_sheets,
    package_final_selfies,
    validate_final_selfies,
)
from cloth_store.selfie_refocus import (
    REFOCUS_METHOD,
    PersonBboxResult,
    RefocusMetrics,
    analyze_mask_body_coverage,
    apply_background_blur,
    assess_review_required,
    build_feathered_alpha,
    compute_background_color_metrics,
    compute_metrics,
    compute_portrait_crop,
    derive_person_bbox_from_localization,
    enrich_person_bbox_with_garments,
    is_incomplete_person_mask,
    metadata_reuse_eligible,
    process_fixture,
    render_crop_only,
    render_crop_refocused,
    should_attempt_mask_recovery,
    subject_bounds_for_crop,
    union_normalized_boxes,
)
from cloth_store.services.catalog import (
    CATALOGUE_DESCRIPTION_PROMPT_PATH,
    DESCRIPTION_MAX_WORDS,
    CatalogService,
)
from cloth_store.services.styling import (
    FASHION_ADVICE_TITLE,
    StylingResolver,
    build_styling_advice_text,
    build_styling_caption,
    resolve_fixture_selfie_asset,
    try_resolve_fixture_selfie_path,
)
from cloth_store.vlm_bbox import (
    parse_full_person_response,
    parse_localization_response,
    validate_full_person_localization,
    validate_localization,
)
from cloth_store.vlm_garment_attributes import (
    parse_garment_attributes_response,
    validate_attribute_field,
    validate_garment_attributes,
)
from cloth_store.web_server import smoke_fetch
from cloth_store.web_storefront import build_storefront_bundle, write_storefront_bundle
from tests.helpers import (
    fixed_generation_now,
    make_mock_generation_response,
    make_smoke_repo_tree,
    write_rgb_square,
)


def test_website_static_catalog_contract(tmp_path: Path) -> None:
    """Static storefront bundle, catalogue services, and web server contract."""
    import socket
    import threading

    from cloth_store.web_server import run_server

    repo_root = Path(__file__).resolve().parents[1]
    catalog_service = CatalogService(
        catalog_json_path=repo_root / "final_catalog/catalog.json",
        final_catalog_root=repo_root / "final_catalog",
        assets_url_prefix="/final_catalog",
    )
    styling_resolver = StylingResolver(
        catalog_service=catalog_service,
        repo_root=repo_root,
        selfies_url_prefix="/data",
        refocus_selfies_url_prefix="/final_selfies",
    )

    assert catalog_service.is_available is True
    summary = catalog_service.summary
    assert int(summary.get("total_items", 0)) == EXPECTED_ITEM_COUNT

    browse = catalog_service.browse()
    assert browse.total == EXPECTED_ITEM_COUNT
    assert all(
        item.image_url.startswith("/final_catalog/") and item.image_url.endswith("/output.png")
        for item in browse.items
    )
    assert all("output_1k" not in item.image_url for item in browse.items)
    assert all(item.description for item in browse.items)
    assert all(";" not in item.description for item in browse.items)
    assert all("_" not in item.description for item in browse.items)
    assert all("outfit_" not in item.description for item in browse.items)
    assert all("front fly" not in item.description.lower() for item in browse.items)
    assert all("button-front fly" not in item.description.lower() for item in browse.items)
    prohibited_phrases = (
        "elegant drape",
        "quiet luminosity",
        "evening poise",
        "office-ready",
        "refined visual interest",
        "poised elegance",
        "sharp formal line",
        "placket",
    )
    for phrase in prohibited_phrases:
        assert all(phrase not in item.description.lower() for item in browse.items)
    assert all(len(item.description.split()) <= DESCRIPTION_MAX_WORDS for item in browse.items)
    prompt_path = repo_root / CATALOGUE_DESCRIPTION_PROMPT_PATH
    assert prompt_path.is_file()
    prompt_text = prompt_path.read_text(encoding="utf-8").lower()
    for required in (
        "fashion-magazine",
        "original description",
        "factual source",
        "do not invent",
        "front fly",
        "elegant drape",
        "20–35 words",
        "finished description",
    ):
        assert required in prompt_text
    assert all(item.labels for item in browse.items)

    tops = catalog_service.browse(display_category="top")
    assert tops.total == 22
    assert all(item.display_category == "top" for item in tops.items)
    assert all(item.role == "top" for item in tops.items)

    blazers = catalog_service.browse(display_category="blazer")
    assert blazers.total == 2
    blazer_ids = {item.catalog_id for item in blazers.items}
    assert blazer_ids == {"outfit_3_top", "outfit_4_top"}
    assert all(item.role == "top" for item in blazers.items)
    assert all(item.garment_class == "blazer" for item in blazers.items)
    assert catalog_service.get_item("outfit_19_top") is None

    role_tops = catalog_service.browse(role="top")
    assert role_tops.total == 24
    assert blazer_ids.issubset({item.catalog_id for item in role_tops.items})

    waistcoat = catalog_service.get_item("outfit_10_top")
    assert waistcoat is not None
    assert waistcoat.display_category == "top"
    assert waistcoat.garment_class == "waistcoat"

    dresses = catalog_service.browse(role="dress")
    assert dresses.total == 2
    dress_ids = {item.catalog_id for item in dresses.items}
    assert dress_ids == {"outfit_29_dress", "outfit_30_dress"}

    search = catalog_service.browse(query="black blazer")
    assert search.items[0].catalog_id == "outfit_3_top"
    assert search.items[0].search_score > 0

    index_html = (repo_root / "src/cloth_store/web/index.html").read_text(encoding="utf-8")
    brand_match = re.search(r'<h1 class="brand-title">([^<]+)</h1>', index_html)
    assert brand_match is not None
    brand_title = brand_match.group(1)
    assert brand_title in index_html
    assert 'id="item-detail-modal"' in index_html
    assert 'id="outfit-generator-modal"' in index_html
    assert 'id="lucky-pair-modal"' in index_html
    assert "Generate an Outfit" in index_html
    assert "I'm Feeling Lucky" in index_html
    assert 'data-category="blazer"' in index_html
    assert ">Blazers</" in index_html
    assert 'id="grid-blazer"' in index_html

    app_js = (repo_root / "src/cloth_store/web/static/app.js").read_text(encoding="utf-8")
    assert "/final_catalog/storefront.json" in app_js
    assert "/api/v1" not in app_js
    assert "source-photos" not in app_js
    assert "buildDetailSlides" in app_js
    assert "output_1k" not in app_js
    assert "advice_title" in app_js
    assert "advice_text" in app_js
    assert "display_category" in app_js
    assert "gridBlazer" in app_js
    assert "Gathering the latest edit from the catalogue." in app_js

    styles_css = (repo_root / "src/cloth_store/web/static/styles.css").read_text(encoding="utf-8")
    assert "--lavender" in styles_css

    sample_item = catalog_service.get_item("outfit_3_top")
    assert sample_item is not None
    assert sample_item.catalog_id == "outfit_3_top"
    assert sample_item.garment_class == "blazer"
    assert sample_item.description.startswith("A black blazer")

    outfit_11 = catalog_service.get_item("outfit_11_top")
    assert outfit_11 is not None
    assert outfit_11.display_name == "Black T-Shirt"

    gray_trousers = catalog_service.get_item("outfit_10_bottom")
    assert gray_trousers is not None
    assert gray_trousers.display_name == "Gray Straight-Fit Trousers"

    slim_gray_trousers = catalog_service.get_item("outfit_15_bottom")
    assert slim_gray_trousers is not None
    assert slim_gray_trousers.display_name == "Gray Slim-Fit Trousers"

    black_blazer = catalog_service.get_item("outfit_3_top")
    assert black_blazer is not None
    assert black_blazer.display_name == "Black Blazer"
    assert "Fit" not in black_blazer.display_name

    for bottom in catalog_service.browse(role="bottom").items:
        name_lower = bottom.display_name.lower()
        assert "straight-leg" not in name_lower
        assert "straight leg" not in name_lower
        assert "fit fit" not in name_lower

    assert catalog_service.get_item("outfit_2_top") is None
    assert catalog_service.get_item("outfit_19_top") is None
    assert catalog_service.get_item("outfit_27_dress") is None
    assert catalog_service.get_item("outfit_31_bottom") is None

    outfit_2_bottom = catalog_service.get_item("outfit_2_bottom")
    assert outfit_2_bottom is not None
    outfit_2_styling = styling_resolver.resolve_for_catalog_item("outfit_2_bottom")
    assert outfit_2_styling is not None
    outfit_2_assoc = next(
        assoc for assoc in outfit_2_styling.associations if assoc.fixture == "outfit_2"
    )
    assert outfit_2_assoc.selfie.available is True
    assert outfit_2_assoc.selfie.image_url == "/final_selfies/outfit_2/crop_neck_down.jpg"
    assert all(partner.catalog_id != "outfit_2_top" for partner in outfit_2_assoc.partners)

    outfit_31_top = catalog_service.get_item("outfit_31_top")
    assert outfit_31_top is not None
    outfit_31_styling = styling_resolver.resolve_for_catalog_item("outfit_31_top")
    assert outfit_31_styling is not None
    outfit_31_assoc = outfit_31_styling.associations[0]
    assert outfit_31_assoc.fixture == "outfit_31"
    assert outfit_31_assoc.selfie.available is True
    assert all(partner.catalog_id != "outfit_31_bottom" for partner in outfit_31_assoc.partners)

    white_trousers_styling = styling_resolver.resolve_for_catalog_item("outfit_22_bottom")
    assert white_trousers_styling is not None
    outfit_19_assoc = next(
        assoc for assoc in white_trousers_styling.associations if assoc.fixture == "outfit_19"
    )
    assert outfit_19_assoc.selfie.available is True
    assert outfit_19_assoc.selfie.image_url == "/final_selfies/outfit_19/crop_neck_down.jpg"
    assert all(partner.catalog_id != "outfit_19_top" for partner in outfit_19_assoc.partners)

    outfit_5_assoc = next(
        assoc for assoc in white_trousers_styling.associations if assoc.fixture == "outfit_5"
    )
    assert outfit_5_assoc.selfie.available is True
    assert outfit_5_assoc.selfie.image_url == "/final_selfies/outfit_5/crop_neck_down.jpg"
    assert all(partner.catalog_id != "outfit_5_bottom" for partner in outfit_5_assoc.partners)
    assert catalog_service.get_item("outfit_5_bottom") is None

    outfit_candidates = styling_resolver.list_outfit_candidates()
    assert all(candidate.fixture != "outfit_27" for candidate in outfit_candidates)
    assert catalog_service.browse(query="outfit 27 dress").total == 0
    assert catalog_service.browse(query="drawstring").total == 0
    excluded_catalog_ids = {
        "outfit_2_top",
        "outfit_19_top",
        "outfit_27_dress",
        "outfit_31_bottom",
    }
    for query in ("green checkered blazer", "pink floral print", "drawstring waist"):
        hits = catalog_service.browse(query=query)
        assert excluded_catalog_ids.isdisjoint({item.catalog_id for item in hits.items})

    top_styling = styling_resolver.resolve_for_catalog_item("outfit_10_top")
    assert top_styling is not None
    assert top_styling.catalog_id == "outfit_10_top"
    assert top_styling.display_name == "Black Waistcoat"
    assert len(top_styling.associations) == 1
    top_association = top_styling.associations[0]
    assert top_association.fixture == "outfit_10"
    assert top_association.selfie.available is True
    assert top_association.selfie.image_url == "/final_selfies/outfit_10/crop_neck_down.jpg"

    outfit_14_styling = styling_resolver.resolve_for_catalog_item("outfit_14_top")
    assert outfit_14_styling is not None
    assert (
        outfit_14_styling.associations[0].selfie.image_url
        == "/final_selfies/outfit_14/crop_neck_down.jpg"
    )

    outfit_29_asset = resolve_fixture_selfie_asset("outfit_29", repo_root=repo_root)
    assert outfit_29_asset is not None
    assert outfit_29_asset.variant == "crop_neck_down"
    assert outfit_29_asset.source_path.name == "crop_neck_down.jpg"

    outfit_30_asset = resolve_fixture_selfie_asset("outfit_30", repo_root=repo_root)
    assert outfit_30_asset is not None
    assert outfit_30_asset.variant == "crop_neck_down"

    for fixture_num in range(1, 32):
        fixture_id = f"outfit_{fixture_num}"
        asset = resolve_fixture_selfie_asset(fixture_id, repo_root=repo_root)
        assert asset is not None, fixture_id
        assert asset.variant == "crop_neck_down", fixture_id
        assert "crop_neck_down.jpg" in asset.image_url, fixture_id
        assert "crop_refocused.jpg" not in asset.image_url, fixture_id
        assert "crop_only.jpg" not in asset.image_url, fixture_id

    refocus_asset = resolve_fixture_selfie_asset("outfit_10", repo_root=repo_root)
    assert refocus_asset is not None
    assert refocus_asset.variant == "crop_neck_down"
    assert refocus_asset.source_path.name == "crop_neck_down.jpg"

    fallback_root = tmp_path / "fallback_selfies"
    fallback_fixture = fallback_root / "outfit_10"
    fallback_fixture.mkdir(parents=True)
    shutil.copy2(
        repo_root / "final_selfies/outfit_10/crop_refocused.jpg",
        fallback_fixture / "crop_refocused.jpg",
    )
    meta_no_privacy = json.loads(
        (repo_root / "final_selfies/outfit_10/metadata.json").read_text(encoding="utf-8")
    )
    meta_no_privacy.pop("privacy_variant", None)
    (fallback_fixture / "metadata.json").write_text(json.dumps(meta_no_privacy), encoding="utf-8")
    fallback_asset = resolve_fixture_selfie_asset(
        "outfit_10",
        repo_root=tmp_path,
        final_selfies_root=Path("fallback_selfies"),
    )
    assert fallback_asset is not None
    assert fallback_asset.variant == "crop_refocused"

    review_root = tmp_path / "review_selfies"
    review_fixture = review_root / "outfit_14"
    review_fixture.mkdir(parents=True)
    shutil.copy2(
        repo_root / "final_selfies/outfit_14/crop_only.jpg",
        review_fixture / "crop_only.jpg",
    )
    meta_review = json.loads(
        (repo_root / "final_selfies/outfit_14/metadata.json").read_text(encoding="utf-8")
    )
    meta_review.pop("privacy_variant", None)
    (review_fixture / "metadata.json").write_text(json.dumps(meta_review), encoding="utf-8")
    review_asset = resolve_fixture_selfie_asset(
        "outfit_14",
        repo_root=tmp_path,
        final_selfies_root=Path("review_selfies"),
    )
    assert review_asset is not None
    assert review_asset.variant == "crop_only"
    assert top_association.advice_title == FASHION_ADVICE_TITLE
    assert top_association.advice_text == "Black Waistcoat with gray straight-fit trousers."

    bottom_styling = styling_resolver.resolve_for_catalog_item("outfit_10_bottom")
    assert bottom_styling is not None
    outfit_10_bottom_assoc = next(
        assoc for assoc in bottom_styling.associations if assoc.fixture == "outfit_10"
    )
    assert (
        outfit_10_bottom_assoc.advice_text == "Gray Straight-Fit Trousers with a black waistcoat."
    )

    outfit_candidates = styling_resolver.list_outfit_candidates()
    assert len(outfit_candidates) >= 20
    outfit_10_candidate = next(c for c in outfit_candidates if c.fixture == "outfit_10")
    assert outfit_10_candidate.top.catalog_id == "outfit_10_top"
    assert outfit_10_candidate.bottom.catalog_id == "outfit_10_bottom"

    generated = styling_resolver.select_outfit_candidate(seed=7)
    assert generated is not None
    repeat = styling_resolver.select_outfit_candidate(seed=7)
    assert repeat.fixture == generated.fixture

    lucky_counts = styling_resolver.lucky_look_candidate_counts()
    assert lucky_counts["top_bottom"] > 0
    assert lucky_counts["blazer_top_bottom"] > 0
    assert lucky_counts["blazer_dress"] > 0

    lucky_candidates = styling_resolver.list_lucky_look_candidates()
    top_bottom_looks = [look for look in lucky_candidates if look.look_type == "top_bottom"]
    blazer_top_bottom_looks = [
        look for look in lucky_candidates if look.look_type == "blazer_top_bottom"
    ]
    blazer_dress_looks = [look for look in lucky_candidates if look.look_type == "blazer_dress"]
    assert top_bottom_looks
    assert blazer_top_bottom_looks
    assert blazer_dress_looks

    for look in lucky_candidates:
        assert look.pieces
        assert 2 <= len(look.pieces) <= 3
        assert look.look_type_label
        assert look.summary
        assert look.note
        assert "selfie" not in look.to_dict()
        for piece in look.pieces:
            assert piece.catalog_id
            assert piece.kind in {"top", "blazer", "bottom", "dress"}
            assert piece.image_url.endswith("/output.png")

    sample_top_bottom = top_bottom_looks[0]
    assert len(sample_top_bottom.pieces) == 2
    assert {piece.kind for piece in sample_top_bottom.pieces} == {"top", "bottom"}

    sample_blazer_outfit = blazer_top_bottom_looks[0]
    assert len(sample_blazer_outfit.pieces) == 3
    assert {piece.kind for piece in sample_blazer_outfit.pieces} == {
        "blazer",
        "top",
        "bottom",
    }

    sample_blazer_dress = blazer_dress_looks[0]
    assert len(sample_blazer_dress.pieces) == 2
    assert {piece.kind for piece in sample_blazer_dress.pieces} == {"blazer", "dress"}

    documented_pairs = styling_resolver.documented_top_bottom_pairs()
    for look in top_bottom_looks:
        top_id = next(p.catalog_id for p in look.pieces if p.kind == "top")
        bottom_id = next(p.catalog_id for p in look.pieces if p.kind == "bottom")
        assert (top_id, bottom_id) not in documented_pairs

    lucky = styling_resolver.select_lucky_look(seed=11)
    assert lucky is not None
    repeat_lucky = styling_resolver.select_lucky_look(seed=11)
    assert repeat_lucky.look_type == lucky.look_type
    assert [piece.catalog_id for piece in repeat_lucky.pieces] == [
        piece.catalog_id for piece in lucky.pieces
    ]

    excluded_ids = tuple(piece.catalog_id for piece in lucky.pieces)
    different = styling_resolver.select_lucky_look(exclude_catalog_ids=excluded_ids, seed=11)
    if styling_resolver.list_lucky_look_candidates():
        assert different is None or excluded_ids != tuple(
            piece.catalog_id for piece in different.pieces
        )

    bundle = build_storefront_bundle(repo_root=repo_root)
    assert bundle["total_items"] == EXPECTED_ITEM_COUNT
    assert len(bundle["outfit_candidates"]) == len(outfit_candidates)
    assert bundle["lucky_look_candidates"]
    assert bundle["lucky_look_candidate_counts"]["top_bottom"] == lucky_counts["top_bottom"]
    assert "lucky-piece-template" in index_html
    assert "pickLuckyLook" in app_js
    assert "renderLuckyLook" in app_js
    assert "lucky_look_candidates" in app_js
    assert "lucky-piece-template" in app_js
    assert "filterLuckyPool" in app_js
    assert "LUCKY_RECENT_HISTORY_LIMIT" in app_js
    assert "pickLuckyLookFromBag" in app_js

    from tests.lucky_selection_mirror import (
        lucky_look_key_piece_ids,
        lucky_look_signature,
        lucky_recent_history_entry,
        pick_lucky_look,
        simulate_lucky_clicks,
    )

    lucky_payload = [look.to_dict() for look in lucky_candidates]
    first = pick_lucky_look(lucky_payload, seed=11)
    assert first is not None
    repeat = pick_lucky_look(lucky_payload, seed=11)
    assert lucky_look_signature(repeat) == lucky_look_signature(first)

    history = [lucky_recent_history_entry(first)]
    immediate_repeat = pick_lucky_look(lucky_payload, recent_history=history, seed=99)
    assert immediate_repeat is not None
    assert lucky_look_signature(immediate_repeat) != lucky_look_signature(first)

    blazer_heavy = [
        look
        for look in lucky_payload
        if look["look_type"] == "blazer_top_bottom"
        and any(p["catalog_id"] == "outfit_3_top" for p in look["pieces"])
    ][:6]
    if len(blazer_heavy) >= 2:
        alt_blazer = next(
            look
            for look in lucky_payload
            if look["look_type"] == "blazer_top_bottom"
            and all(
                p["catalog_id"] != "outfit_3_top" for p in look["pieces"] if p["kind"] == "blazer"
            )
        )
        history = [lucky_recent_history_entry(blazer_heavy[0])]
        next_look = pick_lucky_look(blazer_heavy + [alt_blazer], recent_history=history, seed=5)
        assert next_look is not None
        assert "outfit_3_top" not in lucky_look_key_piece_ids(next_look)

    tiny_pool = lucky_payload[:1]
    tiny_next = pick_lucky_look(
        tiny_pool,
        recent_history=[lucky_recent_history_entry(tiny_pool[0])],
        seed=3,
    )
    assert tiny_next is not None

    sequence = simulate_lucky_clicks(lucky_payload, clicks=6, seed=21)
    assert len(sequence) == 6
    for previous, current in zip(sequence, sequence[1:], strict=False):
        assert lucky_look_signature(previous) != lucky_look_signature(current)
    look_types = [look["look_type"] for look in sequence]
    if len({look_type for look_type in look_types}) > 1:
        assert any(
            previous != current
            for previous, current in zip(look_types, look_types[1:], strict=False)
        )
    storefront_path = tmp_path / "storefront.json"
    write_storefront_bundle(bundle, output_path=storefront_path)
    assert storefront_path.is_file()

    from cloth_store.static_bundle import build_static_bundle, validate_static_bundle

    static_bundle_dir = tmp_path / "lavani-closet"
    build_static_bundle(
        repo_root=repo_root,
        output_dir=static_bundle_dir,
        zip_path=None,
    )
    static_report = validate_static_bundle(static_bundle_dir, run_http_smoke=True)
    assert static_report["total_items"] == EXPECTED_ITEM_COUNT
    assert static_report.get("direct_file_smoke", {}).get("status") == "ok"
    assert static_report.get("direct_file_smoke", {}).get("requires_launcher") is False
    index_html = (static_bundle_dir / "index.html").read_text(encoding="utf-8")
    assert 'href="static/styles.css"' in index_html
    assert 'src="static/app.js"' in index_html
    assert 'id="storefront-data"' in index_html
    assert not re.search(r'(?:href|src)="/static/', index_html)
    assert (static_bundle_dir / "assets/selfies/outfit_30/crop_neck_down.jpg").is_file()
    assert (static_bundle_dir / "assets/selfies/outfit_14/crop_neck_down.jpg").is_file()
    static_storefront = json.loads((static_bundle_dir / "data/storefront.json").read_text())
    for candidate in static_storefront["outfit_candidates"]:
        selfie_url = candidate.get("selfie", {}).get("image_url", "")
        if selfie_url:
            assert "crop_neck_down.jpg" in selfie_url
            assert "crop_refocused.jpg" not in selfie_url
            assert "crop_only.jpg" not in selfie_url
    assert (static_bundle_dir / "assets/catalogue/outfit_30/dress/output.png").is_file()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = run_server(repo_root=repo_root, host="127.0.0.1", port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = smoke_fetch(base, "/")
        assert status == 200
        assert brand_title.encode() in body
        status, body = smoke_fetch(base, "/final_catalog/outfit_3/top/output.png")
        assert status == 200
        assert body[:8] == b"\x89PNG\r\n\x1a\n"
        status, body = smoke_fetch(base, "/final_selfies/outfit_10/crop_neck_down.jpg")
        assert status == 200
        assert body[:2] == b"\xff\xd8"
    finally:
        server.shutdown()
        server.server_close()

    assert build_styling_advice_text("Black Waistcoat", ("Gray Trousers",)) == (
        "Black Waistcoat with gray trousers."
    )
    assert build_styling_caption("Black Waistcoat", ("Gray Trousers",)) == (
        "Black Waistcoat with gray trousers."
    )

    missing_catalog = tmp_path / "missing_catalog.json"
    missing_catalog.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "namespace": "test",
                "items": [
                    {
                        "catalog_id": "outfit_99_top",
                        "display_name": "orphan top",
                        "role": "top",
                        "fixture": "outfit_99",
                        "garment_id": "outfit_99_top",
                        "observation_ids": ["outfit_99_top"],
                        "alias_observation_ids": [],
                        "source_observations": [
                            {
                                "observation_id": "outfit_99_top",
                                "fixture": "outfit_99",
                                "role": "top",
                                "canonical": True,
                                "indexed": True,
                                "display_name": "orphan top",
                            }
                        ],
                        "garment_class_normalized": "blouse",
                        "garment_subtype": None,
                        "facets": {
                            "colors": {"value": "red", "source": "manifest"},
                            "garment_class": {"value": "blouse", "source": "manifest"},
                            "material": {"value": None, "source": "unknown"},
                            "pattern": {"value": "solid", "source": "manifest"},
                            "closure": {"value": None, "source": "unknown"},
                            "finish": {"value": None, "source": "unknown"},
                            "sheen": {"value": None, "source": "unknown"},
                            "neckline_collar": {"value": None, "source": "unknown"},
                            "silhouette_style": {"value": None, "source": "unknown"},
                            "sleeve_length": {"value": None, "source": "unknown"},
                            "role": {"value": "top", "source": "manifest"},
                        },
                        "images": {
                            "output_512": {"path": "outfit_99/top/output.png"},
                            "output_1k": {"path": "outfit_99/top/output_1k.png"},
                        },
                        "tags": ["top", "outfit_99"],
                        "template": {"template_id": "top_full_sleeve"},
                        "provenance": {},
                        "retrieval": {"search_text": "orphan top", "lexical_only": True},
                    }
                ],
                "summary": {"total_items": 1, "facets": {}},
            }
        ),
        encoding="utf-8",
    )
    orphan_service = CatalogService(
        catalog_json_path=missing_catalog,
        final_catalog_root=tmp_path / "final_catalog",
    )
    orphan_resolver = StylingResolver(
        catalog_service=orphan_service,
        repo_root=tmp_path,
    )
    orphan_styling = orphan_resolver.resolve_for_catalog_item("outfit_99_top")
    assert orphan_styling is not None
    assert orphan_styling.associations[0].selfie.available is False
    assert orphan_styling.associations[0].selfie.image_url is None
    assert try_resolve_fixture_selfie_path("outfit_99", repo_root=tmp_path) is None
    assert orphan_resolver.list_outfit_candidates() == ()
    assert orphan_resolver.select_outfit_candidate(seed=1) is None
    assert orphan_resolver.list_lucky_look_candidates() == ()
    assert orphan_resolver.select_lucky_look(seed=1) is None


def test_vlm_bbox_parsing_and_validation() -> None:
    """VLM localization contracts, malformed rejection, and fenced JSON parsing."""
    valid_payloads = [
        {
            "layout": "separates",
            "top": [0.1, 0.2, 0.4, 0.5],
            "bottom": [0.15, 0.45, 0.35, 0.9],
        },
        {"layout": "dress", "dress": [0.2, 0.1, 0.8, 0.95]},
    ]
    for payload in valid_payloads:
        result = validate_localization(payload)
        assert result["layout"] == payload["layout"]
        for role in ("top", "bottom", "dress"):
            if role in payload:
                assert result[role] == pytest.approx(payload[role])

    rejects = [
        (
            {
                "layout": "separates",
                "top": [0.1, 0.2, 0.4, 0.5],
                "bottom": [0.15, 0.45, 0.35, 0.9],
                "confidence": 0.9,
            },
            "confidence",
        ),
        (
            {
                "layout": "dress",
                "top": [0.1, 0.2, 0.4, 0.5],
                "bottom": [0.15, 0.45, 0.35, 0.9],
            },
            "unexpected keys",
        ),
        (
            {
                "layout": "separates",
                "top": [0.4, 0.2, 0.1, 0.5],
                "bottom": [0.15, 0.45, 0.35, 0.9],
            },
            "x_min",
        ),
    ]
    for payload, match in rejects:
        with pytest.raises(ValueError, match=match):
            validate_localization(payload)

    with pytest.raises(ValueError, match="valid JSON"):
        parse_localization_response("{not json")

    raw = json.dumps({"layout": "separates", "dress": [0.1, 0.2, 0.8, 0.95]})
    with pytest.raises(ValueError, match="unexpected keys"):
        parse_localization_response(raw)

    fenced = """Here is the result:
```json
{
  "layout": "separates",
  "top": [100, 200, 400, 500],
  "bottom": [150, 450, 350, 900]
}
```
"""
    parsed = parse_localization_response(fenced)
    assert parsed["layout"] == "separates"
    assert parsed["top"] == [0.1, 0.2, 0.4, 0.5]
    assert parsed["bottom"] == [0.15, 0.45, 0.35, 0.9]

    attribute_payload = {
        "attributes": {
            "garment_class": {
                "value": "office_blouse",
                "confidence": "high",
                "observation_type": "observed",
                "evidence": "long-sleeve blouse silhouette",
            },
            "dominant_color": {
                "value": "deep red",
                "confidence": "high",
                "observation_type": "observed",
                "evidence": "uniform red pixels across garment",
            },
            "likely_material": {
                "value": "satin-like woven fabric",
                "confidence": "medium",
                "observation_type": "inferred",
                "evidence": "soft highlights on folds",
            },
            "surface_sheen": {
                "value": "soft satin-like reflectivity",
                "confidence": "high",
                "observation_type": "observed",
                "evidence": "diffused highlights, not mirror glare",
            },
            "texture_pattern": {
                "value": "solid",
                "confidence": "high",
                "observation_type": "observed",
                "evidence": "no print or embroidery visible",
            },
            "weave_finish": {
                "value": "smooth satin finish",
                "confidence": "medium",
                "observation_type": "inferred",
                "evidence": "fine surface without visible weave grid",
            },
            "closures_details": {
                "value": "small collar button",
                "confidence": "high",
                "observation_type": "observed",
                "evidence": "dark button at collar center",
            },
            "sleeve_cuff_neckline": {
                "value": "full sleeves, gathered cuffs, standing collar",
                "confidence": "high",
                "observation_type": "observed",
                "evidence": "wrist gathers and mandarin collar visible",
            },
        }
    }
    attrs = validate_garment_attributes(attribute_payload)
    assert attrs["dominant_color"]["confidence"] == "high"
    fenced_attrs = f"```json\n{json.dumps(attribute_payload)}\n```"
    assert parse_garment_attributes_response(fenced_attrs)["surface_sheen"]["value"].startswith(
        "soft satin"
    )

    numeric_conf = validate_attribute_field(
        "dominant_color",
        {
            "value": "crimson",
            "confidence": 0.92,
            "observation_type": "observed",
            "evidence": "pixels",
        },
    )
    assert numeric_conf["confidence"] == "high"


def test_sam_masks_and_catalog_cutouts(tmp_path: Path) -> None:
    """SAM crop/mask helpers and catalog cutout centering on white canvas."""
    box = [0.40, 0.40, 0.60, 0.60]
    padded = pad_normalized_box(box, pad_fraction=0.10, image_width=1000, image_height=800)
    assert padded[0] < box[0] and padded[1] < box[1]
    assert padded[2] > box[2] and padded[3] > box[3]
    assert all(0.0 <= value <= 1.0 for value in padded)

    edge_box = [0.0, 0.0, 0.05, 0.05]
    edge_padded = pad_normalized_box(edge_box, pad_fraction=0.50, image_width=100, image_height=100)
    assert edge_padded[0] == 0.0 and edge_padded[1] == 0.0

    original_box = [0.45, 0.78, 0.51, 0.83]
    image_width, image_height = 1000, 1600
    padded_box = pad_normalized_box(
        original_box,
        pad_fraction=0.10,
        image_width=image_width,
        image_height=image_height,
    )
    crop_bounds = normalized_xyxy_to_pixel_crop(
        padded_box,
        image_width=image_width,
        image_height=image_height,
    )
    x0, y0, _, _ = crop_bounds
    crop_w = crop_bounds[2] - crop_bounds[0]
    crop_h = crop_bounds[3] - crop_bounds[1]
    ox0, oy0, ox1, oy1 = normalized_xyxy_to_pixel_box(
        original_box,
        image_width=image_width,
        image_height=image_height,
    )
    prompt = original_box_to_crop_prompt(
        original_box,
        crop_bounds,
        image_width=image_width,
        image_height=image_height,
    )
    assert prompt == pytest.approx([ox0 - x0, oy0 - y0, ox1 - x0, oy1 - y0])
    assert 0.0 <= prompt[0] < prompt[2] <= float(crop_w)
    assert 0.0 <= prompt[1] < prompt[3] <= float(crop_h)

    crop_mask = np.zeros((30, 20), dtype=bool)
    crop_mask[5:15, 5:15] = True
    full_mask = place_crop_mask_in_full_image(
        crop_mask,
        (10, 20, 30, 50),
        image_width=100,
        image_height=100,
    )
    assert full_mask.shape == (100, 100)
    assert not full_mask[0:20, 0:10].any()
    assert full_mask[25, 15]
    with pytest.raises(ValueError, match="does not match crop bounds"):
        place_crop_mask_in_full_image(
            np.zeros((5, 5), dtype=bool),
            (0, 0, 10, 10),
            image_width=20,
            image_height=20,
        )

    rgb = Image.new("RGB", (100, 200), color=(10, 20, 30))
    garment_mask = np.zeros((200, 100), dtype=bool)
    garment_mask[40:160, 20:80] = True
    cutout = render_catalog_cutout(rgb, garment_mask, role="top")
    assert cutout.size == (CUTOUT_CANVAS_SIZE, CUTOUT_CANVAS_SIZE)
    assert cutout.mode == "RGB"

    arr = np.array(cutout)
    non_white = np.any(arr != 255, axis=2)
    ys, xs = np.where(non_white)
    cx = (xs.min() + xs.max()) / 2
    cy = (ys.min() + ys.max()) / 2
    assert cx == pytest.approx(CUTOUT_CANVAS_SIZE / 2, abs=2)
    assert cy == pytest.approx(CUTOUT_CANVAS_SIZE / 2, abs=2)
    max_side = int(round(CUTOUT_CANVAS_SIZE * (1.0 - 2.0 * CUTOUT_MARGIN_FRACTION)))
    assert (xs.max() - xs.min() + 1) <= max_side
    assert (ys.max() - ys.min() + 1) <= max_side
    assert tuple(arr[0, 0]) == WHITE_BACKGROUND

    alpha_mask = np.zeros((4, 4), dtype=bool)
    alpha_mask[1:3, 1:3] = True
    masked = masked_rgb_cutout(Image.new("RGB", (4, 4), color=(255, 0, 0)), alpha_mask)
    assert masked.getpixel((0, 0)) == WHITE_BACKGROUND
    assert masked.getpixel((1, 1)) == (255, 0, 0)

    empty_mask = np.zeros((20, 20), dtype=bool)
    with pytest.raises(ValueError, match="empty mask for role 'bottom'"):
        render_catalog_cutout(
            Image.new("RGB", (20, 20), color=(0, 0, 0)),
            empty_mask,
            role="bottom",
        )

    # Selfie refocus: person bbox derivation, portrait crop geometry, blur-only compositing.
    localization = {
        "layout": "separates",
        "top": [0.30, 0.35, 0.55, 0.58],
        "bottom": [0.32, 0.55, 0.52, 0.90],
    }
    person_bbox = derive_person_bbox_from_localization(localization)
    assert person_bbox.provenance == "garment_union_asymmetric_v1"
    assert 0.0 <= person_bbox.confidence <= 1.0
    union = union_normalized_boxes([localization["top"], localization["bottom"]])
    assert person_bbox.box[0] <= union[0]
    assert person_bbox.box[2] >= union[2]
    assert person_bbox.box[1] < union[1]
    assert person_bbox.box[3] >= union[3]

    image_w, image_h = 400, 600
    person_mask = np.zeros((image_h, image_w), dtype=bool)
    person_mask[120:520, 100:300] = True
    crop = compute_portrait_crop(image_w, image_h, person_mask)
    assert crop.output_width == crop.x1 - crop.x0
    assert crop.output_height == crop.y1 - crop.y0
    assert crop.aspect_label in {"4:5", "3:4"}
    assert pytest.approx(crop.aspect_ratio, rel=0.02) == crop.output_width / crop.output_height
    assert crop.x0 <= 100 and crop.x1 >= 300
    assert crop.y0 <= 120 and crop.y1 >= 520

    selfie_rgb = Image.new("RGB", (image_w, image_h), color=(40, 80, 120))
    selfie_arr = np.array(selfie_rgb)
    selfie_arr[person_mask] = (200, 100, 50)
    selfie_rgb = Image.fromarray(selfie_arr, mode="RGB")
    crop_only = render_crop_only(selfie_rgb, crop)
    crop_refocused = render_crop_refocused(selfie_rgb, crop, person_mask)
    assert crop_only.size == (crop.output_width, crop.output_height)
    assert crop_refocused.size == crop_only.size

    alpha = build_feathered_alpha(person_mask[crop.y0 : crop.y1, crop.x0 : crop.x1])
    refocus_arr = apply_background_blur(np.array(crop_only), alpha)
    core = alpha >= 0.99
    if core.any():
        assert np.array_equal(refocus_arr[core], np.array(crop_only)[core])
    background = alpha < 0.05
    assert background.any()
    assert not np.array_equal(refocus_arr[background], np.array(crop_only)[background])

    color_preservation, lum_preservation = compute_background_color_metrics(
        np.array(crop_only), refocus_arr, alpha
    )
    assert color_preservation >= 0.95
    assert lum_preservation >= 0.95

    metrics = compute_metrics(
        image_width=image_w,
        image_height=image_h,
        person_mask=person_mask,
        crop=crop,
        crop_only_rgb=np.array(crop_only),
        crop_refocused_rgb=np.array(crop_refocused),
    )
    assert metrics.person_pixel_preservation >= 0.95
    assert metrics.background_color_preservation >= 0.95
    assert metrics.background_luminance_preservation >= 0.95
    assert 0.0 <= metrics.retained_background_fraction <= 1.0

    crop_repeat = compute_portrait_crop(image_w, image_h, person_mask)
    assert crop_repeat == crop

    dress_localization = {
        "layout": "dress",
        "dress": [0.34, 0.36, 0.59, 0.76],
    }
    dress_bbox = derive_person_bbox_from_localization(dress_localization)
    assert dress_bbox.source_roles == ["dress"]
    assert dress_bbox.box[1] < dress_localization["dress"][1]

    review_flag, review_reason = assess_review_required(
        person_bbox=person_bbox,
        metrics=metrics,
    )
    assert review_flag is False
    clipped_metrics = compute_metrics(
        image_width=image_w,
        image_height=image_h,
        person_mask=person_mask,
        crop=crop,
        crop_only_rgb=np.array(crop_only),
        crop_refocused_rgb=np.array(crop_refocused),
    )
    clipped_metrics = RefocusMetrics(
        subject_clipped=True,
        retained_background_fraction=clipped_metrics.retained_background_fraction,
        background_reduction_fraction=clipped_metrics.background_reduction_fraction,
        person_mask_coverage=clipped_metrics.person_mask_coverage,
        person_pixel_preservation=clipped_metrics.person_pixel_preservation,
        edge_halo_score=clipped_metrics.edge_halo_score,
        background_color_preservation=clipped_metrics.background_color_preservation,
        background_luminance_preservation=clipped_metrics.background_luminance_preservation,
    )
    clipped_review, clipped_reason = assess_review_required(
        person_bbox=person_bbox,
        metrics=clipped_metrics,
    )
    assert clipped_review is True
    assert clipped_reason == "subject_clipped"

    torso_only_mask = np.zeros((image_h, image_w), dtype=bool)
    torso_only_mask[220:320, 120:280] = True
    dress_localization_for_mask = {
        "layout": "dress",
        "dress": [0.30, 0.20, 0.70, 0.80],
    }
    person_bbox_for_mask = [0.28, 0.18, 0.72, 0.82]
    incomplete, incomplete_reason = is_incomplete_person_mask(
        torso_only_mask,
        person_bbox_for_mask,
        dress_localization_for_mask,
        image_width=image_w,
        image_height=image_h,
    )
    assert incomplete is True
    assert incomplete_reason == "torso_only_mask"
    torso_coverage = analyze_mask_body_coverage(
        torso_only_mask,
        person_bbox_for_mask,
        image_width=image_w,
        image_height=image_h,
    )
    assert torso_coverage["head_hair"] == 0.0
    assert torso_coverage["torso"] > 0.0

    full_person_mask = np.zeros((image_h, image_w), dtype=bool)
    full_person_mask[100:520, 100:300] = True
    complete, complete_reason = is_incomplete_person_mask(
        full_person_mask,
        person_bbox_for_mask,
        dress_localization_for_mask,
        image_width=image_w,
        image_height=image_h,
    )
    assert complete is False
    assert complete_reason is None

    from cloth_store.selfie_privacy_crop import (
        build_neck_down_config_from_mask,
        compute_neck_down_crop,
        estimate_collarbone_cutoff_y_from_mask,
        estimate_face_bottom_cutoff_y_from_mask,
        render_neck_down_from_refocused,
    )

    neck_base_crop = compute_portrait_crop(image_w, image_h, person_mask)
    face_bottom_y, face_prov = estimate_face_bottom_cutoff_y_from_mask(
        person_mask=person_mask,
        base_crop=neck_base_crop,
        image_height=image_h,
    )
    collarbone_y, _ = estimate_collarbone_cutoff_y_from_mask(
        person_mask=person_mask,
        base_crop=neck_base_crop,
        image_height=image_h,
    )
    assert collarbone_y > face_bottom_y
    neck_config = build_neck_down_config_from_mask(
        person_mask=person_mask,
        base_crop=neck_base_crop,
        image_height=image_h,
        manual_face_bottom_cutoff_y_normalized=face_bottom_y / image_h,
        manual_provenance="manual_review_face_bottom_cutoff_test",
    )
    assert neck_config.face_bottom_provenance == "manual_review_face_bottom_cutoff_test"
    neck_geometry = compute_neck_down_crop(
        image_width=image_w,
        image_height=image_h,
        person_mask=person_mask,
        base_crop=neck_base_crop,
        config=neck_config,
        collarbone_cutoff_y=collarbone_y,
    )
    assert neck_geometry.neck_down_crop.y0 == int(
        round(neck_config.face_bottom_cutoff_y_normalized * image_h)
    )
    assert neck_geometry.neck_down_crop.y1 == neck_base_crop.y1
    assert neck_geometry.output_height == neck_base_crop.y1 - neck_geometry.neck_down_crop.y0
    assert pytest.approx(neck_geometry.neck_down_crop.aspect_ratio, rel=0.02) == 4 / 5
    sub_crop = neck_geometry.sub_crop_from_refocused
    assert sub_crop[0] >= 0 and sub_crop[1] >= 0
    assert sub_crop[2] <= neck_base_crop.output_width
    assert sub_crop[3] <= neck_base_crop.output_height
    refocused_stub = Image.new(
        "RGB",
        (neck_base_crop.output_width, neck_base_crop.output_height),
        color=(30, 60, 90),
    )
    neck_down = render_neck_down_from_refocused(refocused_stub, sub_crop)
    assert neck_down.size == (neck_geometry.output_width, neck_geometry.output_height)
    assert neck_down.size[0] <= refocused_stub.size[0]
    assert neck_down.size[1] <= refocused_stub.size[1]

    qwen_box = [0.32, 0.15, 0.68, 0.88]
    enriched = enrich_person_bbox_with_garments(qwen_box, dress_localization_for_mask)
    assert enriched.provenance == "qwen_full_reflected_person_v1"
    assert enriched.box[0] <= dress_localization_for_mask["dress"][0]
    assert enriched.box[2] >= dress_localization_for_mask["dress"][2]
    assert enriched.box[1] < dress_localization_for_mask["dress"][1]

    subject_bounds = subject_bounds_for_crop(
        torso_only_mask,
        person_bbox_for_mask,
        image_width=image_w,
        image_height=image_h,
    )
    assert subject_bounds[1] < 220
    assert subject_bounds[3] >= 320
    assert subject_bounds[2] >= 280

    recovery_bbox = PersonBboxResult(
        box=person_bbox_for_mask,
        provenance="garment_union_asymmetric_v1",
        confidence=0.8,
        source_roles=["dress"],
    )
    attempt, trigger = should_attempt_mask_recovery(
        person_mask=torso_only_mask,
        person_bbox=recovery_bbox,
        localization=dress_localization_for_mask,
        image_width=image_w,
        image_height=image_h,
    )
    assert attempt is True
    assert trigger == "torso_only_mask"

    crop_with_bbox = compute_portrait_crop(
        image_w,
        image_h,
        torso_only_mask,
        person_bbox=person_bbox_for_mask,
    )
    assert crop_with_bbox.y0 <= subject_bounds[1]
    assert crop_with_bbox.y1 >= subject_bounds[3]

    full_person_payload = parse_full_person_response('{"person":[0.1,0.2,0.9,0.95]}')
    assert validate_full_person_localization(full_person_payload)["person"] == [
        0.1,
        0.2,
        0.9,
        0.95,
    ]

    cloth_repo = Path(__file__).resolve().parents[1]
    range_fixtures = resolve_plan1_fixtures(from_fixture=1, to_fixture=4)
    assert range_fixtures == [f"outfit_{index}" for index in range(1, 5)]
    assert len(plan1_fixture_ids()) == 31

    bench_root = cloth_repo / "bench/selfie_refocus/candidates"
    outfit_1_meta = bench_root / "outfit_1/metadata.json"
    if outfit_1_meta.is_file():
        metadata = json.loads(outfit_1_meta.read_text(encoding="utf-8"))
        assert metadata["parameters"]["refocus_method"] == REFOCUS_METHOD
        source_path = resolve_fixture_source_path("outfit_1", repo_root=cloth_repo)
        assert metadata_reuse_eligible(metadata, source_path=source_path)
        first = process_fixture(
            "outfit_1",
            repo_root=cloth_repo,
            output_root=bench_root,
            json_dir=cloth_repo / "bench/plan1_localization/outputs",
        )
        second = process_fixture(
            "outfit_1",
            repo_root=cloth_repo,
            output_root=bench_root,
            json_dir=cloth_repo / "bench/plan1_localization/outputs",
        )
        assert first.generated_or_reused == "reused"
        assert second.generated_or_reused == "reused"

        final_root = tmp_path / "final_selfies"
        manifest = package_final_selfies(
            repo_root=cloth_repo,
            final_root=final_root,
            bench_root=bench_root,
            fixture_ids=["outfit_1"],
        )
        assert manifest["refocus_method"] == REFOCUS_METHOD
        assert manifest["fixtures"][0]["recommended_variant"] in {"crop_only", "crop_refocused"}
        rerun = package_final_selfies(
            repo_root=cloth_repo,
            final_root=final_root,
            bench_root=bench_root,
            fixture_ids=["outfit_1"],
        )
        assert rerun["skipped_fixtures"] == ["outfit_1"]
        assert validate_final_selfies(repo_root=cloth_repo, final_root=final_root) == []

        sheet_manifest = build_batched_contact_sheets(
            repo_root=cloth_repo,
            final_root=final_root,
            fixtures=manifest["fixtures"],
            batch_size_outfits=4,
        )
        assert sheet_manifest["batch_size_outfits"] == 4
        assert len(sheet_manifest["sheets"]) == 1
        assert sheet_manifest["sheets"][0]["outfits"] == ["outfit_1"]

    from cloth_store.selfie_privacy_crop import (
        NECK_DOWN_METHOD,
        SOURCE_VARIANT_ORIGINAL,
        get_fixture_privacy_override,
        load_privacy_cutoff_overrides,
        process_fixture_privacy_crop,
    )
    from cloth_store.selfie_privacy_packaging import package_privacy_fixture

    if outfit_1_meta.is_file():
        privacy_root = tmp_path / "privacy_final_selfies"
        privacy_bench = cloth_repo / "bench/selfie_refocus/candidates"
        overrides = load_privacy_cutoff_overrides(cloth_repo)
        assert "outfit_1" in overrides.get("overrides", {})
        assert get_fixture_privacy_override(overrides, "outfit_29") is not None
        assert (
            get_fixture_privacy_override(overrides, "outfit_29").source_variant
            == SOURCE_VARIANT_ORIGINAL
        )
        first_privacy = process_fixture_privacy_crop(
            "outfit_1",
            repo_root=cloth_repo,
            candidate_root=privacy_bench,
            overrides=overrides,
        )
        second_privacy = process_fixture_privacy_crop(
            "outfit_1",
            repo_root=cloth_repo,
            candidate_root=privacy_bench,
            overrides=overrides,
        )
        assert first_privacy.generated_or_reused in {"processed", "reused"}
        assert second_privacy.generated_or_reused == "reused"
        assert first_privacy.qc_status != "fail"

        privacy_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(cloth_repo / "final_selfies/outfit_1", privacy_root / "outfit_1")
        package_privacy_fixture(
            repo_root=cloth_repo,
            final_root=privacy_root,
            bench_root=privacy_bench,
            fixture_id="outfit_1",
        )
        fixture_meta = json.loads((privacy_root / "outfit_1/metadata.json").read_text())
        assert fixture_meta["privacy_variant"]["method"] == NECK_DOWN_METHOD
        assert (privacy_root / "outfit_1/crop_neck_down.jpg").is_file()


def test_catalog_template_geometry() -> None:
    """Template canvas invariants and distinctive garment geometry."""
    center_tolerance = 3
    margin_tolerance = 2
    min_margin = int(round(CANVAS_SIZE * MARGIN_FRACTION)) - margin_tolerance
    max_side = int(round(CANVAS_SIZE * (1.0 - 2.0 * MARGIN_FRACTION)))

    for spec in TEMPLATE_SPECS:
        image = render_template_png(spec)
        assert image.size == (CANVAS_SIZE, CANVAS_SIZE)
        assert image.mode == "RGB"
        for corner in (
            (0, 0),
            (CANVAS_SIZE - 1, 0),
            (0, CANVAS_SIZE - 1),
            (CANVAS_SIZE - 1, CANVAS_SIZE - 1),
        ):
            assert image.getpixel(corner) == WHITE_BACKGROUND, spec.id

        min_x, min_y, max_x, max_y = visible_foreground_bounds(image)
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        assert cx == pytest.approx(CANVAS_SIZE / 2, abs=center_tolerance), spec.id
        assert cy == pytest.approx(CANVAS_SIZE / 2, abs=center_tolerance), spec.id
        assert min_x >= min_margin, spec.id
        assert min_y >= min_margin, spec.id
        assert max_x <= CANVAS_SIZE - 1 - min_margin, spec.id
        assert max_y <= CANVAS_SIZE - 1 - min_margin, spec.id
        assert (max_x - min_x + 1) <= max_side + margin_tolerance, spec.id
        assert (max_y - min_y + 1) <= max_side + margin_tolerance, spec.id

    blazer = render_template_png(TEMPLATE_BY_ID["blazer"])
    mid = CANVAS_SIZE // 2
    white_rows = sum(1 for y in range(CANVAS_SIZE) if blazer.getpixel((mid, y)) == WHITE_BACKGROUND)
    assert white_rows >= 20
    assert blazer.getpixel((mid, CANVAS_SIZE // 2)) == WHITE_BACKGROUND

    waistcoat = render_template_png(TEMPLATE_BY_ID["waistcoat_closed"])
    assert TEMPLATE_BY_ID["waistcoat_closed"].top_kind == "waistcoat"
    assert TEMPLATE_BY_ID["waistcoat_closed"].sleeve is None
    assert not TEMPLATE_BY_ID["waistcoat_closed"].cutouts
    assert waistcoat.getpixel((mid, CANVAS_SIZE // 2)) != WHITE_BACKGROUND
    waistcoat_white_rows = sum(
        1 for y in range(CANVAS_SIZE) if waistcoat.getpixel((mid, y)) == WHITE_BACKGROUND
    )
    assert waistcoat_white_rows < white_rows

    full = TEMPLATE_BY_ID["top_full_sleeve"]
    half = TEMPLATE_BY_ID["top_half_sleeve"]
    sleeveless = TEMPLATE_BY_ID["top_sleeveless"]
    assert sleeveless.sleeve == "sleeveless"
    assert sleeveless.top_kind == "generic"
    assert len(sleeveless.polygons) == 1
    assert len(sleeveless.cutouts) == 2
    full_min_x = min(x for polygon in full.polygons for x, _ in polygon)
    half_min_x = min(x for polygon in half.polygons for x, _ in polygon)
    sleeveless_min_x = min(x for polygon in sleeveless.polygons for x, _ in polygon)
    full_max_x = max(x for polygon in full.polygons for x, _ in polygon)
    half_max_x = max(x for polygon in half.polygons for x, _ in polygon)
    assert full_min_x < half_min_x
    assert full_max_x > half_max_x
    assert sleeveless_min_x > half_min_x
    assert sleeveless_min_x > full_min_x

    sleeveless_png = render_template_png(sleeveless)
    half_png = render_template_png(half)
    waistcoat_png = render_template_png(TEMPLATE_BY_ID["waistcoat_closed"])
    mid = CANVAS_SIZE // 2
    sleeveless_shoulder_white = sum(
        1
        for y in range(CANVAS_SIZE // 8, CANVAS_SIZE // 3)
        if sleeveless_png.getpixel((mid // 2, y)) == WHITE_BACKGROUND
        or sleeveless_png.getpixel((CANVAS_SIZE - mid // 2, y)) == WHITE_BACKGROUND
    )
    half_shoulder_white = sum(
        1
        for y in range(CANVAS_SIZE // 8, CANVAS_SIZE // 3)
        if half_png.getpixel((mid // 2, y)) == WHITE_BACKGROUND
        or half_png.getpixel((CANVAS_SIZE - mid // 2, y)) == WHITE_BACKGROUND
    )
    assert sleeveless_shoulder_white > half_shoulder_white
    assert TEMPLATE_BY_ID["waistcoat_closed"].top_kind == "waistcoat"
    assert sleeveless.top_kind != TEMPLATE_BY_ID["waistcoat_closed"].top_kind
    assert waistcoat_png.getpixel((mid, CANVAS_SIZE // 2)) != WHITE_BACKGROUND

    pants = render_template_png(TEMPLATE_BY_ID["pants"])
    assert pants_centerline_gap_rows(pants) > 0

    pencil = render_template_png(TEMPLATE_BY_ID["skirt_pencil"])
    knee = render_template_png(TEMPLATE_BY_ID["skirt_knee_length"])
    long_skirt = render_template_png(TEMPLATE_BY_ID["skirt_long"])
    a_line = render_template_png(TEMPLATE_BY_ID["skirt"])
    pencil_metrics = template_silhouette_width_metrics(pencil)
    knee_metrics = template_silhouette_width_metrics(knee)
    long_metrics = template_silhouette_width_metrics(long_skirt)
    a_line_metrics = template_silhouette_width_metrics(a_line)
    assert pencil_metrics["mid_width_fraction"] < a_line_metrics["mid_width_fraction"]
    assert pencil_metrics["hem_width_fraction"] < a_line_metrics["hem_width_fraction"]
    assert knee_metrics["hem_width_fraction"] < pencil_metrics["hem_width_fraction"]
    assert long_metrics["hem_width_fraction"] > a_line_metrics["hem_width_fraction"]
    assert "skirt_pencil" in TEMPLATE_BY_ID
    assert TEMPLATE_BY_ID["skirt_pencil"].bottom_kind == "skirt_pencil"
    assert TEMPLATE_BY_ID["skirt_knee_length"].bottom_kind == "skirt_knee_length"
    assert TEMPLATE_BY_ID["skirt_long"].bottom_kind == "skirt_long"

    dress = render_template_png(TEMPLATE_BY_ID["dress_knee_length_half_sleeve"])
    half_top = render_template_png(TEMPLATE_BY_ID["top_half_sleeve"])
    dress_metrics = template_silhouette_width_metrics(dress)
    assert TEMPLATE_BY_ID["dress_knee_length_half_sleeve"].top_kind == "dress"
    assert TEMPLATE_BY_ID["dress_knee_length_half_sleeve"].sleeve == "half"
    assert dress_metrics["hem_width_fraction"] > 0.35
    dress_bounds = visible_foreground_bounds(dress)
    half_bounds = visible_foreground_bounds(half_top)
    dress_min_y, dress_max_y = dress_bounds[1], dress_bounds[3]
    half_min_y, half_max_y = half_bounds[1], half_bounds[3]
    assert (dress_max_y - dress_min_y) > (half_max_y - half_min_y)

    full_dress = render_template_png(TEMPLATE_BY_ID["dress_knee_length_full_sleeve"])
    full_dress_metrics = template_silhouette_width_metrics(full_dress)
    assert TEMPLATE_BY_ID["dress_knee_length_full_sleeve"].top_kind == "dress"
    assert TEMPLATE_BY_ID["dress_knee_length_full_sleeve"].sleeve == "full"
    assert full_dress_metrics["hem_width_fraction"] > 0.33
    full_dress_bounds = visible_foreground_bounds(full_dress)
    full_top = render_template_png(TEMPLATE_BY_ID["top_full_sleeve"])
    full_top_bounds = visible_foreground_bounds(full_top)
    assert (full_dress_bounds[3] - full_dress_bounds[1]) > (full_top_bounds[3] - full_top_bounds[1])


def test_catalog_template_selector_and_confidence() -> None:
    """VLM-label normalization, mapping, low-confidence fallbacks, and overrides."""
    assert normalize_garment_class("suit-jacket") == "blazer"
    assert normalize_garment_class("office shirt") == "office_blouse"
    assert normalize_garment_class("jeans") == "trousers"
    assert normalize_garment_class("vest") == "waistcoat"
    assert normalize_sleeve_length("long") == "full"
    assert normalize_sleeve_length("short") == "half"
    assert normalize_sleeve_length("sleeveless") == "sleeveless"
    assert normalize_sleeve_length("three_quarter") is None

    office_full = select_template_from_attributes(
        GarmentAttributes("outfit_6", "top", "office_blouse", "full", None, "office blouse")
    )
    assert office_full.template_id == "top_full_sleeve"
    assert office_full.confidence == "high"

    blazer = select_template_from_attributes(
        GarmentAttributes("outfit_3", "top", "blazer", "full", None, "structured blazer")
    )
    assert blazer.template_id == "blazer"

    waistcoat = select_template_from_attributes(
        GarmentAttributes(
            "outfit_10",
            "top",
            "waistcoat",
            None,
            None,
            "black sleeveless waistcoat",
        )
    )
    assert waistcoat.template_id == "waistcoat_closed"
    assert waistcoat.confidence == "high"

    vest = select_template_from_attributes(
        GarmentAttributes("x", "top", "vest", None, None, "formal vest")
    )
    assert vest.template_id == "waistcoat_closed"
    assert vest.confidence == "high"

    sleeveless_blouse = select_template_from_attributes(
        GarmentAttributes(
            "outfit_13",
            "top",
            "blouse",
            "sleeveless",
            None,
            "pastel pink sleeveless halter lace top",
        )
    )
    assert sleeveless_blouse.template_id == "top_sleeveless"
    assert sleeveless_blouse.confidence == "high"

    blouse_not_waistcoat = select_template_from_attributes(
        GarmentAttributes(
            "x",
            "top",
            "blouse",
            "sleeveless",
            None,
            "sleeveless halter blouse",
        )
    )
    assert blouse_not_waistcoat.template_id == "top_sleeveless"
    assert blouse_not_waistcoat.template_id != "waistcoat_closed"

    pencil = select_template_from_attributes(
        GarmentAttributes("outfit_6", "bottom", "skirt", None, "pencil", "straight skirt")
    )
    assert pencil.template_id == "skirt_pencil"

    dress_sel = select_template_from_attributes(
        GarmentAttributes(
            "outfit_27",
            "dress",
            "dress",
            "half",
            "knee_length",
            "knee-length polo dress",
        )
    )
    assert dress_sel.template_id == "dress_knee_length_half_sleeve"
    assert dress_sel.confidence == "high"

    full_dress_sel = select_template_from_attributes(
        GarmentAttributes(
            "outfit_29",
            "dress",
            "dress",
            "full",
            "knee_length",
            "blush pink lace dress",
        )
    )
    assert full_dress_sel.template_id == "dress_knee_length_full_sleeve"
    assert full_dress_sel.confidence == "high"

    outfit_9_sleeveless = select_template_from_attributes(
        GarmentAttributes(
            "outfit_9",
            "top",
            "blouse",
            "sleeveless",
            None,
            "black sleeveless top",
        ),
        template_override="top_sleeveless",
    )
    assert outfit_9_sleeveless.template_id == "top_sleeveless"
    assert outfit_9_sleeveless.override_applied is True

    long_skirt_sel = select_template_from_attributes(
        GarmentAttributes("outfit_28", "bottom", "skirt", None, "maxi", "long striped skirt")
    )
    assert long_skirt_sel.template_id == "skirt_long"
    assert long_skirt_sel.confidence == "high"

    missing_sleeve = select_template_from_attributes(
        GarmentAttributes("x", "top", "blouse", None, None, "unknown sleeves")
    )
    assert missing_sleeve.confidence == "low"
    assert missing_sleeve.template_id == "top_full_sleeve"

    override = select_template_from_attributes(
        GarmentAttributes("x", "top", "blouse", "full", None, "override case"),
        template_override="blazer",
    )
    assert override.template_id == "blazer"
    assert override.override_applied is True
    assert override.confidence == "high"

    repo_root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (repo_root / "bench/catalog_generation/manifest.json").read_text(encoding="utf-8")
    )
    discrepancies = validate_all_manifest_cases(
        manifest,
        attributes_path=repo_root / "bench/plan1_localization/garment_attributes.json",
    )
    assert discrepancies == []
    records = load_garment_attributes(
        repo_root / "bench/plan1_localization/garment_attributes.json"
    )
    assert len(records) == 59

    # Source path resolution: data/outfit_N.jpeg for fixtures 25-31 and full manifest
    repo_root = Path(__file__).resolve().parents[1]
    for fid in plan1_fixture_ids():
        resolved = resolve_fixture_source_path(fid, repo_root=repo_root)
        assert resolved.is_file(), f"missing source for {fid}: {resolved}"
        assert resolved.parent.name == "data" or fid in resolved.name
    assert resolve_fixture_source_path("outfit_25", repo_root=repo_root).is_file()
    assert resolve_fixture_source_path("outfit_27", repo_root=repo_root).is_file()
    assert resolve_fixture_source_path("outfit_28", repo_root=repo_root).is_file()
    assert resolve_fixture_source_path("outfit_29", repo_root=repo_root).is_file()
    assert resolve_fixture_source_path("outfit_30", repo_root=repo_root).is_file()
    assert resolve_fixture_source_path("outfit_31", repo_root=repo_root).is_file()


def test_gemini_credential_config_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Gemini credential resolution precedence, missing-key errors, and redaction."""
    assert NANO_BANANA_2_MODEL_ID == "gemini-3.1-flash-image"
    config = GeminiCatalogConfig()
    assert config.model_id == NANO_BANANA_2_MODEL_ID
    assert GEMINI_API_KEY_ENV not in repr(config)

    assert redact_secret(None) == "<missing>"
    assert redact_secret("short") == "***"
    assert redact_secret("abcdefghijklmnop") == "abcd...mnop"

    creds_file = tmp_path / "credentials.env"
    creds_file.write_text(f"{GEMINI_API_KEY_ENV}=file-key\n", encoding="utf-8")
    monkeypatch.delenv(GEMINI_API_KEY_ENV, raising=False)
    monkeypatch.setenv(GEMINI_API_KEY_ENV, "env-key")
    assert resolve_gemini_api_key(credentials_file=creds_file) == "env-key"

    monkeypatch.delenv(GEMINI_API_KEY_ENV, raising=False)
    creds_file.write_text(
        f"export {GEMINI_API_KEY_ENV}='file-key-value'\n",
        encoding="utf-8",
    )
    assert resolve_gemini_api_key(credentials_file=creds_file) == "file-key-value"

    missing = tmp_path / "missing.env"
    with (
        patch("cloth_store.gemini_catalog.DEFAULT_CREDENTIALS_FALLBACKS", ()),
        pytest.raises(GeminiCredentialsError) as exc_info,
    ):
        resolve_gemini_api_key(credentials_file=missing)
    assert GEMINI_API_KEY_ENV in str(exc_info.value)
    assert "file-key-value" not in str(exc_info.value)

    override = tmp_path / "override.env"
    assert credential_fallback_paths(override)[0] == override

    with patch("google.genai.Client") as mock_client_cls:
        with patch(
            "cloth_store.gemini_catalog.resolve_gemini_api_key",
            return_value="resolved-key",
        ):
            build_gemini_client()
        mock_client_cls.assert_called_once_with(api_key="resolved-key")

    mock_client = MagicMock()
    mock_client.models.get.return_value = MagicMock(display_name="Nano Banana 2")
    ok = check_model_availability(config=GeminiCatalogConfig(), client=mock_client)
    assert ok == AvailabilityCheckResult(
        ok=True,
        model_id=NANO_BANANA_2_MODEL_ID,
        display_name="Nano Banana 2",
    )

    with patch(
        "cloth_store.gemini_catalog.build_gemini_client",
        side_effect=GeminiCredentialsError("missing key"),
    ):
        cred_err = check_model_availability(config=GeminiCatalogConfig())
    assert cred_err.ok is False
    assert cred_err.error == "missing key"

    cleaned = sanitize_api_error(
        "Auth failed for AIzaSyDUMMYKEY012345678901234567890 and sk-abcdefghijklmnop"
    )
    assert "AIza" not in cleaned
    assert "sk-" not in cleaned


def test_gemini_request_artifact_provenance_and_prompt_policy(tmp_path: Path) -> None:
    """Deterministic request artifacts, provenance guards, and prompt policy."""
    repo_root = tmp_path / "repo"
    cutout = repo_root / ALLOWED_CUTOUT_PREFIX / SMOKE_FIXTURE_ID / f"catalog_{SMOKE_ROLE}.png"
    template = repo_root / ALLOWED_TEMPLATE_PREFIX / f"{SMOKE_TEMPLATE_ID}.png"
    write_rgb_square(cutout, color=(200, 120, 80))
    write_rgb_square(template, color=(90, 90, 90))

    validate_source_provenance(
        f"{ALLOWED_CUTOUT_PREFIX}{SMOKE_FIXTURE_ID}/catalog_{SMOKE_ROLE}.png",
        image_role=IMAGE_ROLE_GARMENT_IDENTITY,
        fixture_id=SMOKE_FIXTURE_ID,
        role=SMOKE_ROLE,
    )
    for bad_path in (
        "bench/plan2_reconstruction/outputs/template_projection/outfit_1/top_projected.png",
        "bench/catalog_templates/generated/top_full_sleeve_projected.png",
    ):
        with pytest.raises(CatalogRequestArtifactError, match="derived experiment output"):
            validate_source_provenance(
                bad_path,
                image_role=IMAGE_ROLE_GARMENT_IDENTITY,
                fixture_id=SMOKE_FIXTURE_ID,
                role=SMOKE_ROLE,
            )

    prompt = build_catalog_generation_prompt(
        fixture_id=SMOKE_FIXTURE_ID,
        role=SMOKE_ROLE,
        template_id=SMOKE_TEMPLATE_ID,
    )
    validate_prompt_constraints(prompt)
    assert "Image 1" in prompt
    assert "Image 2" in prompt
    assert prompt_descriptor_leakage(prompt) == ()
    assert "closed" in template_prompt_policy("top_full_sleeve").lower()
    blazer_policy = template_prompt_policy("blazer").lower()
    assert "closed" in blazer_policy
    assert "present an open" not in blazer_policy
    waistcoat_policy = template_prompt_policy("waistcoat_closed").lower()
    assert "closed" in waistcoat_policy
    assert "buttoned" in waistcoat_policy
    assert "sleeveless" in waistcoat_policy
    assert "open the front" in waistcoat_policy
    sleeveless_policy = template_prompt_policy("top_sleeveless").lower()
    assert "sleeveless" in sleeveless_policy
    assert "do not add sleeves" in sleeveless_policy
    assert "waistcoat" in sleeveless_policy
    dress_policy = template_prompt_policy("dress_knee_length_half_sleeve").lower()
    assert "one-piece" in dress_policy
    assert "waistband separation" in dress_policy
    assert "blouse-plus-skirt" in dress_policy
    full_dress_policy = template_prompt_policy("dress_knee_length_full_sleeve").lower()
    assert "one-piece" in full_dress_policy
    assert "full/long sleeves" in full_dress_policy
    assert (
        prompt_descriptor_leakage(
            build_catalog_generation_prompt(
                fixture_id="outfit_6",
                role="bottom",
                template_id="skirt_pencil",
            )
        )
        == ()
    )

    payload = build_request_artifact(
        repo_root=repo_root,
        fixture_id=SMOKE_FIXTURE_ID,
        role=SMOKE_ROLE,
        template_id=SMOKE_TEMPLATE_ID,
    )
    assert payload["request_layout"]["part_order"][0] == IMAGE_ROLE_GARMENT_IDENTITY
    assert payload["request_layout"]["part_order"][1] == IMAGE_ROLE_TEMPLATE_GEOMETRY
    if len(payload["request_layout"]["part_order"]) == 3:
        assert payload["request_layout"]["part_order"][2] == IMAGE_ROLE_GARMENT_DETAIL
    images = payload["images"]
    assert images[0]["order"] == 1
    assert images[0]["sha256"] == sha256_file(repo_root / images[0]["path"])

    first = serialize_request_artifact(payload)
    second = serialize_request_artifact(payload)
    assert first == second
    assert first.endswith("\n")

    artifact_path = repo_root / "bench/catalog_generation/artifacts/smoke.request.json"
    write_request_artifact(payload, output_path=artifact_path)
    loaded = json.loads(artifact_path.read_text(encoding="utf-8"))
    validate_request_artifact(loaded, repo_root=repo_root)

    tampered = dict(payload)
    tampered["images"] = list(payload["images"])
    tampered["images"][0] = dict(payload["images"][0])
    tampered["images"][0]["sha256"] = "0" * 64
    with pytest.raises(CatalogRequestArtifactError, match="sha256 mismatch"):
        validate_request_artifact(tampered, repo_root=repo_root)

    vlm_attrs = {
        "garment_class": {
            "value": "office_blouse",
            "confidence": "high",
            "observation_type": "observed",
            "evidence": "blouse cut",
        },
        "dominant_color": {
            "value": "deep red",
            "confidence": "high",
            "observation_type": "observed",
            "evidence": "red fabric",
        },
        "likely_material": {
            "value": "satin-like fabric",
            "confidence": "medium",
            "observation_type": "inferred",
            "evidence": "sheen on folds",
        },
        "surface_sheen": {
            "value": "soft satin-like reflectivity",
            "confidence": "high",
            "observation_type": "observed",
            "evidence": "diffused highlights",
        },
        "texture_pattern": {
            "value": "solid",
            "confidence": "high",
            "observation_type": "observed",
            "evidence": "no print",
        },
        "weave_finish": {
            "value": "smooth",
            "confidence": "medium",
            "observation_type": "inferred",
            "evidence": "fine surface",
        },
        "closures_details": {
            "value": "collar button",
            "confidence": "high",
            "observation_type": "observed",
            "evidence": "visible button",
        },
        "sleeve_cuff_neckline": {
            "value": "full sleeves, gathered cuffs",
            "confidence": "high",
            "observation_type": "observed",
            "evidence": "long sleeves",
        },
    }
    vlm_prompt, injected = build_vlm_conditioned_prompt(
        fixture_id="outfit_6",
        role="top",
        template_id=SMOKE_TEMPLATE_ID,
        attributes=vlm_attrs,
    )
    validate_prompt_constraints(vlm_prompt)
    assert "dominant_color" in injected
    assert "soft satin-like reflectivity" in vlm_prompt.lower()
    assert "glossy" in vlm_prompt.lower()
    assert "metallic" in vlm_prompt.lower()
    clause, clause_injected = build_vlm_attribute_clause(vlm_attrs)
    assert "dominant_color" in clause_injected
    assert "likely_material" not in clause_injected

    validate_geometry_source_path(
        "bench/catalog_generation/outputs/nano_banana_2/catalog_production_v1/outfit_4/top_1k_raw.png"
    )
    validate_derived_geometry_path(
        "bench/catalog_generation/candidates/outfit_3_top_presentation_geometry_v1/"
        "derived_geometry_from_outfit_4_top.png"
    )
    geo_prompt, geo_injected = build_geometry_candidate_prompt(
        fixture_id="outfit_3",
        role="top",
        template_id="blazer",
        geometry_source_fixture="outfit_4",
        attributes=vlm_attrs,
        include_detail_reference=False,
    )
    validate_prompt_constraints(geo_prompt)
    assert "do not transfer any white" in geo_prompt.lower()
    assert "image 2 controls geometry" in geo_prompt.lower()
    assert "round neck" in geo_prompt.lower()
    assert IMAGE_ROLE_DERIVED_GEOMETRY == "derived_geometry"
    assert GEOMETRY_CANDIDATE_NAMESPACE == "outfit_3_top_presentation_geometry_v1"

    corrected_prompt, corrected_injected = build_user_corrected_prompt(
        fixture_id="outfit_6",
        role="top",
        template_id=SMOKE_TEMPLATE_ID,
        attributes=vlm_attrs,
        user_override=DEFAULT_OUTFIT_6_OVERRIDE,
        include_detail_reference=True,
    )
    validate_prompt_constraints(corrected_prompt)
    assert USER_OVERRIDE_GARMENT_CLASS == "shirt"
    assert "User override (highest precedence)" in corrected_prompt
    assert "garment class: shirt" in corrected_prompt.lower()
    assert "crew neck" in corrected_prompt.lower()
    assert "round neck" in corrected_prompt.lower()
    assert "collarless blouse" in corrected_prompt.lower()
    assert "garment_class" not in corrected_injected
    assert "sleeve_cuff_neckline" not in corrected_injected
    assert "dominant_color" in corrected_injected
    override_clause = build_user_override_clause(DEFAULT_OUTFIT_6_OVERRIDE)
    assert "structured shirt" in override_clause.lower()
    assert "text_only" not in override_clause

    override_fixture = Path(__file__).resolve().parents[1] / (
        "bench/catalog_generation/overrides/outfit_6_top.override.json"
    )
    if override_fixture.is_file():
        loaded_override = load_user_override(override_fixture)
        assert loaded_override.garment_class == "shirt"
        assert "garment_class" in loaded_override.overridden_vlm_fields
        assert len(loaded_override.prompt_lines) == 6

    outfit_3_override = Path(__file__).resolve().parents[1] / (
        "bench/catalog_generation/overrides/outfit_3_top.override.json"
    )
    if outfit_3_override.is_file():
        geo_override = load_user_override(outfit_3_override)
        assert geo_override.geometry_reference_override is not None
        assert geo_override.input_role_policy is not None
        assert geo_override.input_role_policy.include_detail_reference is False
        assert "outfit_4" in geo_override.geometry_reference_override.geometry_source_fixture


def test_gemini_generation_one_call_mocked(tmp_path: Path) -> None:
    """Mocked Gemini generation: one call, output normalization, metadata redaction."""
    repo_root = make_smoke_repo_tree(tmp_path)
    artifact_path = repo_root / "bench/catalog_generation/artifacts/smoke.request.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    contents = build_generation_contents(artifact=artifact, repo_root=repo_root)
    assert contents[0].startswith("Image 1 (garment_identity):")
    assert isinstance(contents[1], Image.Image)
    assert contents[-1] == artifact["prompt"]
    assert len(contents) == len(artifact["images"]) * 2 + 1

    settings = generation_request_settings(model_id=NANO_BANANA_2_MODEL_ID, image_size="1K")
    assert settings["aspect_ratio"] == "1:1"
    assert settings["response_modalities"] == ["TEXT", "IMAGE"]

    png = Image.new("RGB", (1024, 1024), color=(240, 240, 240))
    buffer = io.BytesIO()
    png.save(buffer, format="PNG")
    response = make_mock_generation_response()
    images = extract_response_images(response)
    assert len(images) == 1
    assert images[0].image.size == (1024, 1024)

    normalized, info = normalize_catalog_output(png, target_size=512)
    assert normalized.size == (512, 512)
    assert info["resize_applied"] is True

    metadata = build_run_metadata(
        artifact_path="bench/catalog_generation/artifacts/smoke.request.json",
        artifact=artifact,
        request_settings=settings,
        request_utc="2026-08-01T00:00:00+00:00",
        elapsed_seconds=1.23,
        raw_path="bench/catalog_generation/outputs/nano_banana_2/outfit_1/top_raw.png",
        raw_width=1024,
        raw_height=1024,
        raw_sha256="a" * 64,
        raw_mime_type="image/png",
        catalog_path="bench/catalog_generation/outputs/nano_banana_2/outfit_1/top.png",
        catalog_sha256="b" * 64,
        normalization={"resize_applied": True, "resize_method": "LANCZOS"},
        generation_calls=1,
        image_size="1K",
    )
    serialized = serialize_run_metadata(metadata)
    assert "AIza" not in serialized
    assert GEMINI_API_KEY_ENV not in serialized
    assert metadata["generation_calls"] == 1

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = make_mock_generation_response()
    outputs = run_catalog_generation(
        repo_root=repo_root,
        artifact_path=artifact_path,
        client=mock_client,
        now=fixed_generation_now(),
        legacy_names=True,
    )
    mock_client.models.generate_content.assert_called_once()
    assert outputs.raw_path.name == "top_raw.png"
    assert outputs.catalog_path.name == "top.png"
    assert outputs.metadata["generation_calls"] == 1
    with Image.open(outputs.catalog_path) as catalog:
        assert catalog.size == (512, 512)

    empty_client = MagicMock()
    empty_client.models.generate_content.return_value = type(
        "R", (), {"parts": [], "candidates": []}
    )()
    with pytest.raises(CatalogGenerationError, match="no image parts"):
        run_catalog_generation(
            repo_root=repo_root,
            artifact_path=artifact_path,
            client=empty_client,
        )


def test_production_pipeline_idempotency_and_output_contract(tmp_path: Path) -> None:
    """Production pipeline reuse, 1K output contract, and local 512 derivation."""
    assert CANONICAL_IMAGE_SIZE == "1K"

    source = Image.new("RGB", (1024, 1024), (180, 20, 40))
    normalized, meta = normalize_catalog_output(source, target_size=512)
    assert normalized.size == (512, 512)
    assert meta["resize_applied"] is True
    out_dir = tmp_path / "production"
    out_dir.mkdir()
    local_paths = CanonicalOutputPaths(
        raw_1k_path=out_dir / "top_1k_raw.png",
        catalog_512_path=out_dir / "top.png",
        metadata_path=out_dir / "top.run.json",
    )
    source.save(local_paths.raw_1k_path)
    normalized.save(local_paths.catalog_512_path)
    local_paths.metadata_path.write_text(
        json.dumps({"generation_calls": 1}) + "\n",
        encoding="utf-8",
    )
    validate_canonical_outputs(local_paths)

    sanitized = sanitize_canonical_metadata(
        {"prompt_text": "secret prompt", "prompt_sha256": "abc", "generation_calls": 1}
    )
    assert "prompt_text" not in sanitized
    assert sanitized["prompt_sha256"] == "abc"
    assert estimate_canonical_cost_usd(count=2) == pytest.approx(0.134)

    cloth_repo = Path(__file__).resolve().parents[1]
    assert PRODUCTION_NAMESPACE == "catalog_production_v1"
    assert PIPELINE_GENERATION_MODE == "catalog_pipeline"

    top_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_6",
        role="top",
    )
    assert top_plan.override_applied is True
    assert top_plan.template_id == "top_full_sleeve"
    assert top_plan.review_required is False
    assert "user_override" in top_plan.artifact
    assert top_plan.artifact["prompt_policy_version"] == 6

    bottom_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_6",
        role="bottom",
    )
    assert bottom_plan.override_applied is False
    assert bottom_plan.template_id == "skirt_pencil"
    assert bottom_plan.artifact["prompt_policy_version"] == 5

    outfit_25_bottom_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_25",
        role="bottom",
    )
    assert outfit_25_bottom_plan.template_id == "pants"
    assert (
        check_identity_alias_reuse_eligible(
            repo_root=cloth_repo,
            observation_id="outfit_25_bottom",
        )
        is not None
    )

    dry_outfit_25_bottom = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_25",
        role="bottom",
        dry_run=True,
    )
    assert dry_outfit_25_bottom.generation_calls == 0
    assert dry_outfit_25_bottom.plan.reuse_status == "reuse_identity_alias"

    outfit_26_bottom_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_26",
        role="bottom",
    )
    assert outfit_26_bottom_plan.template_id == "skirt_pencil"
    assert outfit_26_bottom_plan.review_required is False
    assert (
        check_identity_alias_reuse_eligible(
            repo_root=cloth_repo,
            observation_id="outfit_26_bottom",
        )
        is not None
    )

    dry_outfit_26_bottom = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_26",
        role="bottom",
        dry_run=True,
    )
    assert dry_outfit_26_bottom.generation_calls == 0
    assert dry_outfit_26_bottom.plan.reuse_status == "reuse_identity_alias"
    assert dry_outfit_26_bottom.plan.billable is False

    outfit_8_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_8",
        role="top",
    )
    assert outfit_8_plan.override_applied is True
    assert outfit_8_plan.template_id == "top_half_sleeve"
    assert "zip" in outfit_8_plan.artifact["prompt"].lower()

    outfit_9_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_9",
        role="top",
    )
    assert outfit_9_plan.override_applied is True
    assert outfit_9_plan.template_id == "top_sleeveless"
    assert "user_override" in outfit_9_plan.artifact
    assert "do not add sleeves" in outfit_9_plan.artifact["prompt"].lower()

    outfit_18_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_18",
        role="top",
    )
    assert outfit_18_plan.override_applied is True
    assert outfit_18_plan.template_id == "top_sleeveless"
    assert "large" in outfit_18_plan.artifact["prompt"].lower()

    dry_top = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_6",
        role="top",
        dry_run=True,
    )
    assert dry_top.status == "dry_run"
    assert dry_top.generation_calls == 0
    assert dry_top.plan.reuse_status == "reuse_production"

    outfit_3_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_3",
        role="top",
    )
    assert outfit_3_plan.override_applied is True
    assert outfit_3_plan.template_id == "blazer"
    assert outfit_3_plan.artifact["prompt_policy_version"] == 1
    assert "geometry_reference_override" in outfit_3_plan.artifact
    geo_images = outfit_3_plan.artifact["images"]
    assert geo_images[1]["role"] == "derived_geometry"
    assert len(geo_images) == 2
    assert outfit_3_plan.artifact["detail_reference_provenance"]["included"] is False

    dry_outfit_3 = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_3",
        role="top",
        dry_run=True,
    )
    assert dry_outfit_3.status == "dry_run"
    assert dry_outfit_3.generation_calls == 0
    assert dry_outfit_3.plan.reuse_status == "reuse_production"

    outfit_10_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_10",
        role="top",
    )
    assert outfit_10_plan.template_id == "waistcoat_closed"
    assert outfit_10_plan.review_required is False

    dry_outfit_10 = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_10",
        role="top",
        dry_run=True,
    )
    assert dry_outfit_10.status == "dry_run"
    assert dry_outfit_10.generation_calls == 0
    assert dry_outfit_10.plan.reuse_status == "reuse_production"

    outfit_13_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_13",
        role="top",
    )
    assert outfit_13_plan.override_applied is True
    assert outfit_13_plan.template_id == "top_sleeveless"
    assert "user_override" in outfit_13_plan.artifact
    assert outfit_13_plan.artifact["prompt_policy_version"] == 6

    outfit_7_plan = build_pipeline_plan(
        repo_root=cloth_repo,
        fixture_id="outfit_7",
        role="top",
    )
    assert outfit_7_plan.override_applied is True
    assert outfit_7_plan.template_id == "top_sleeveless"
    assert outfit_7_plan.artifact["template_id"] == "top_sleeveless"
    assert "user_override" in outfit_7_plan.artifact
    assert outfit_7_plan.artifact["images"][1]["path"].endswith("top_sleeveless.png")

    dry_outfit_13 = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_13",
        role="top",
        dry_run=True,
    )
    assert dry_outfit_13.status == "dry_run"
    assert dry_outfit_13.generation_calls == 0
    assert dry_outfit_13.plan.reuse_status == "reuse_production"

    prod_meta_path = (
        cloth_repo / "bench/catalog_generation/outputs/nano_banana_2/"
        "catalog_production_v1/outfit_3/top.run.json"
    )
    prod_meta = json.loads(prod_meta_path.read_text(encoding="utf-8"))
    assert prod_meta["generation_calls"] == 0
    assert (
        prod_meta["production_policy"]["promoted_from_candidate"]
        == "outfit_3_top_presentation_geometry_v1"
    )
    assert prod_meta["prompt_sha256"] == sha256_text(outfit_3_plan.artifact["prompt"])

    ref_artifact = json.loads(
        (
            cloth_repo / "bench/catalog_generation/artifacts/"
            "outfit_6_top_top_full_sleeve.user_corrected.request.json"
        ).read_text(encoding="utf-8")
    )
    assert sha256_text(top_plan.artifact["prompt"]) == sha256_text(ref_artifact["prompt"])
    assert (
        check_reference_promotion_eligible(
            repo_root=cloth_repo,
            artifact=top_plan.artifact,
        )
        is None
    )

    dry_bottom = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_6",
        role="bottom",
        dry_run=True,
    )
    assert dry_bottom.generation_calls == 0
    assert dry_bottom.plan.estimated_cost_usd == 0.0

    sanitized_pipeline = sanitize_pipeline_metadata(
        {"prompt_text": "secret", "generation_mode": PIPELINE_GENERATION_MODE}
    )
    assert "prompt_text" not in sanitized_pipeline

    final_root = cloth_repo / "final_catalog"
    registry_path = cloth_repo / "bench/catalog_generation/garment_identities.json"
    registry_payload = load_garment_identity_registry(registry_path)
    identity_map = validate_garment_identity_registry(
        payload=registry_payload,
        final_root=final_root,
        repo_root=cloth_repo,
    )
    exclusion_registry_path = default_exclusion_registry_path(cloth_repo)
    exclusion_payload = load_exclusion_registry(exclusion_registry_path)
    exclusion_map = validate_exclusion_registry(
        payload=exclusion_payload,
        final_root=final_root,
        identity_map=identity_map,
    )
    assert len(exclusion_map.excluded_observations) == EXPECTED_EXCLUDED_OBSERVATION_COUNT
    assert exclusion_map.excluded_observations == frozenset(
        {
            "outfit_2_top",
            "outfit_19_top",
            "outfit_27_dress",
            "outfit_31_bottom",
        }
    )
    assert len(identity_map.groups) == 7
    expected_groups = [
        (
            "outfit_3_bottom",
            "outfit_15_bottom",
            "garment_gray_trousers_002",
        ),
        ("outfit_16_bottom", "outfit_15_bottom", "garment_gray_trousers_002"),
        ("outfit_23_bottom", "outfit_24_bottom", "garment_khaki_slim_trousers_001"),
        ("outfit_26_bottom", "outfit_6_bottom", "garment_black_pencil_skirt_001"),
        ("outfit_16_top", "outfit_22_top", "garment_white_button_down_shirt_001"),
    ]
    for alias_id, canonical_id, garment_id in expected_groups:
        assert identity_map.observation_to_garment[alias_id] == garment_id
        assert identity_map.observation_to_garment[canonical_id] == garment_id
        assert alias_id in identity_map.alias_observations
        assert canonical_id not in identity_map.alias_observations
    assert (
        identity_map.observation_to_garment["outfit_20_top"]
        == "garment_white_button_down_shirt_001"
    )
    assert "outfit_20_top" in identity_map.alias_observations
    assert (
        identity_map.observation_to_garment["outfit_25_bottom"] == "garment_khaki_slim_trousers_001"
    )
    assert "outfit_25_bottom" in identity_map.alias_observations

    conflict_payload = json.loads(registry_path.read_text(encoding="utf-8"))
    conflict_payload["groups"].append(
        {
            "garment_id": "garment_conflict_test_001",
            "canonical_observation_id": "outfit_23_bottom",
            "observation_ids": ["outfit_23_bottom", "outfit_22_bottom"],
            "reason": "user_confirmed",
        }
    )
    with pytest.raises(GarmentIdentityError, match="appears in multiple identity groups"):
        validate_garment_identity_registry(
            payload=conflict_payload,
            final_root=final_root,
            repo_root=cloth_repo,
        )

    index_payload = build_catalog_index(repo_root=cloth_repo, final_root=final_root)
    assert len(index_payload["items"]) == EXPECTED_ITEM_COUNT
    assert index_payload["summary"]["observation_count"] == EXPECTED_OBSERVATION_COUNT
    assert index_payload["summary"]["unique_garment_count"] == EXPECTED_ITEM_COUNT
    assert (
        index_payload["summary"]["excluded_observation_count"]
        == EXPECTED_EXCLUDED_OBSERVATION_COUNT
    )
    assert index_payload["summary"]["merged_identity_count"] == 7
    by_id = {item["catalog_id"]: item for item in index_payload["items"]}
    for alias_id, canonical_id, garment_id in expected_groups:
        if garment_id in {
            "garment_white_button_down_shirt_001",
            "garment_khaki_slim_trousers_001",
            "garment_tan_trousers_001",
            "garment_off_white_trousers_001",
            "garment_gray_trousers_001",
            "garment_gray_trousers_002",
        }:
            continue
        assert alias_id not in by_id
        merged = by_id[canonical_id]
        assert merged["garment_id"] == garment_id
        assert set(merged["observation_ids"]) == {alias_id, canonical_id}
        assert merged["alias_observation_ids"] == [alias_id]
        assert merged["identity"]["reason"] == "user_confirmed"
        assert merged["identity"]["canonical_selection_reason"]
        assert len(merged["source_observations"]) == 2
    white_shirt = by_id["outfit_22_top"]
    assert white_shirt["garment_id"] == "garment_white_button_down_shirt_001"
    assert set(white_shirt["observation_ids"]) == {
        "outfit_16_top",
        "outfit_20_top",
        "outfit_22_top",
    }
    assert white_shirt["alias_observation_ids"] == ["outfit_16_top", "outfit_20_top"]
    assert "outfit_16_top" not in by_id
    assert "outfit_20_top" not in by_id
    assert white_shirt["display_name"] == "white long-sleeve button-down shirt"
    khaki_trousers = by_id["outfit_24_bottom"]
    assert khaki_trousers["garment_id"] == "garment_khaki_slim_trousers_001"
    assert set(khaki_trousers["observation_ids"]) == {
        "outfit_23_bottom",
        "outfit_24_bottom",
        "outfit_25_bottom",
    }
    assert khaki_trousers["alias_observation_ids"] == ["outfit_23_bottom", "outfit_25_bottom"]
    assert "outfit_23_bottom" not in by_id
    assert "outfit_25_bottom" not in by_id
    white_trousers = by_id["outfit_22_bottom"]
    assert white_trousers["garment_id"] == "garment_off_white_trousers_001"
    assert set(white_trousers["observation_ids"]) == {
        "outfit_5_bottom",
        "outfit_17_bottom",
        "outfit_18_bottom",
        "outfit_19_bottom",
        "outfit_20_bottom",
        "outfit_21_bottom",
        "outfit_22_bottom",
    }
    assert white_trousers["alias_observation_ids"] == [
        "outfit_5_bottom",
        "outfit_17_bottom",
        "outfit_18_bottom",
        "outfit_19_bottom",
        "outfit_20_bottom",
        "outfit_21_bottom",
    ]
    assert "outfit_5_bottom" not in by_id
    assert "outfit_17_bottom" not in by_id
    assert "outfit_18_bottom" not in by_id
    assert "outfit_19_bottom" not in by_id
    assert "outfit_20_bottom" not in by_id
    assert "outfit_21_bottom" not in by_id
    assert white_trousers["display_name"] == "white relaxed-fit trousers"
    assert white_trousers["facets"]["fit"]["value"] == "relaxed"
    assert white_trousers["facets"]["colors"]["value"] == "white"
    assert white_trousers["facets"]["colors"]["source"] == "user_confirmed_identity"
    assert white_trousers["facets"]["fit"]["source"] == "user_confirmed_identity"
    assert "relaxed fit trousers" in white_trousers["tags"]
    assert "white" in white_trousers["tags"]
    assert "off-white" not in white_trousers["tags"]
    assert "beige" not in white_trousers["tags"]
    assert white_trousers["images"]["output_512"]["path"] == "outfit_22/bottom/output.png"
    gray_trousers = by_id["outfit_10_bottom"]
    assert gray_trousers["garment_id"] == "garment_gray_trousers_001"
    assert set(gray_trousers["observation_ids"]) == {
        "outfit_10_bottom",
        "outfit_11_bottom",
        "outfit_12_bottom",
        "outfit_13_bottom",
        "outfit_14_bottom",
    }
    assert gray_trousers["alias_observation_ids"] == [
        "outfit_11_bottom",
        "outfit_12_bottom",
        "outfit_13_bottom",
        "outfit_14_bottom",
    ]
    assert "outfit_11_bottom" not in by_id
    assert "outfit_12_bottom" not in by_id
    assert "outfit_13_bottom" not in by_id
    assert "outfit_14_bottom" not in by_id
    assert gray_trousers["display_name"] == "gray trousers"
    assert gray_trousers["facets"]["colors"]["value"] == "gray"
    assert gray_trousers["facets"]["colors"]["source"] == "user_confirmed_identity"
    assert "dark gray" not in gray_trousers["tags"]
    assert "charcoal gray" not in gray_trousers["tags"]
    assert gray_trousers["images"]["output_512"]["path"] == "outfit_10/bottom/output.png"
    slim_gray_trousers = by_id["outfit_15_bottom"]
    assert slim_gray_trousers["garment_id"] == "garment_gray_trousers_002"
    assert set(slim_gray_trousers["observation_ids"]) == {
        "outfit_3_bottom",
        "outfit_4_bottom",
        "outfit_15_bottom",
        "outfit_16_bottom",
    }
    assert slim_gray_trousers["alias_observation_ids"] == [
        "outfit_3_bottom",
        "outfit_4_bottom",
        "outfit_16_bottom",
    ]
    assert "outfit_3_bottom" not in by_id
    assert "outfit_4_bottom" not in by_id
    assert "outfit_16_bottom" not in by_id
    assert slim_gray_trousers["images"]["output_512"]["path"] == "outfit_15/bottom/output.png"
    assert slim_gray_trousers["display_name"] == "slim fit gray trousers"
    assert slim_gray_trousers["facets"]["fit"]["value"] == "slim"
    assert slim_gray_trousers["facets"]["fit"]["source"] == "user_confirmed_identity"
    assert slim_gray_trousers["facets"]["colors"]["value"] == "gray"
    assert slim_gray_trousers["facets"]["colors"]["source"] == "user_confirmed_identity"
    assert "slim fit trousers" in slim_gray_trousers["tags"]
    assert "dark gray" not in slim_gray_trousers["tags"]
    tan_trousers = by_id["outfit_2_bottom"]
    assert tan_trousers["garment_id"] == "garment_tan_trousers_001"
    assert set(tan_trousers["observation_ids"]) == {
        "outfit_1_bottom",
        "outfit_2_bottom",
        "outfit_7_bottom",
        "outfit_8_bottom",
        "outfit_9_bottom",
    }
    assert tan_trousers["alias_observation_ids"] == [
        "outfit_1_bottom",
        "outfit_7_bottom",
        "outfit_8_bottom",
        "outfit_9_bottom",
    ]
    assert "outfit_1_bottom" not in by_id
    assert "outfit_7_bottom" not in by_id
    assert "outfit_8_bottom" not in by_id
    assert "outfit_9_bottom" not in by_id
    assert tan_trousers["display_name"] == "tan straight-fit trousers"
    assert tan_trousers["facets"]["fit"]["value"] == "straight"
    assert tan_trousers["facets"]["fit"]["source"] == "user_confirmed_identity"
    assert tan_trousers["facets"]["colors"]["value"] == "tan"
    assert tan_trousers["facets"]["colors"]["source"] == "user_confirmed_identity"
    assert "straight fit trousers" in tan_trousers["tags"]
    assert "tan" in tan_trousers["tags"]
    assert "brown" not in tan_trousers["tags"]
    assert "taupe" not in tan_trousers["tags"]
    assert "outfit_12_top" in by_id
    assert "outfit_18_top" in by_id
    assert "outfit_24_top" in by_id
    assert "outfit_10_top" in by_id
    validate_catalog_index(
        payload=index_payload,
        final_root=final_root,
        repo_root=cloth_repo,
        identity_map=identity_map,
        exclusion_map=exclusion_map,
    )

    khaki_trousers = by_id["outfit_24_bottom"]
    assert khaki_trousers["display_name"] == "straight-fit khaki trousers"
    assert khaki_trousers["facets"]["fit"]["value"] == "straight"
    assert khaki_trousers["facets"]["fit"]["source"] == "user_confirmed_identity"
    assert "straight-fit khaki trousers" in khaki_trousers["tags"]
    assert "khaki" in khaki_trousers["tags"]
    assert "tan" not in khaki_trousers["tags"]
    assert "brown" not in khaki_trousers["tags"]

    first_serialized = serialize_catalog_index(index_payload)
    second_payload = build_catalog_index(repo_root=cloth_repo, final_root=final_root)
    second_serialized = serialize_catalog_index(second_payload)
    assert first_serialized == second_serialized

    outfit_6_top = by_id["outfit_6_top"]
    assert outfit_6_top["garment_class_normalized"] == "shirt"
    assert outfit_6_top["facets"]["garment_class"]["source"] == "user_override"
    assert outfit_6_top["facets"]["sheen"]["value"] == "soft restrained satin-like sheen"
    assert outfit_6_top["facets"]["sheen"]["source"] == "user_override"
    assert "structured collar" in outfit_6_top["facets"]["neckline_collar"]["value"]
    assert outfit_6_top["facets"]["garment_class"]["value"] != "office_blouse"

    outfit_3_top = by_id["outfit_3_top"]
    assert outfit_3_top["garment_class_normalized"] == "blazer"
    assert outfit_3_top["user_override"]["geometry_reference"] is not None
    assert outfit_3_top["provenance"]["promoted_from_candidate"] == (
        "outfit_3_top_presentation_geometry_v1"
    )

    outfit_10_top = by_id["outfit_10_top"]
    assert outfit_10_top["garment_class_normalized"] == "waistcoat"
    assert outfit_10_top["template"]["template_id"] == "waistcoat_closed"
    assert "waistcoat" in outfit_10_top["tags"]
    assert "vest" in outfit_10_top["tags"]
    assert "waistcoat_closed" in outfit_10_top["tags"]

    outfit_13_top = by_id["outfit_13_top"]
    assert outfit_13_top["template"]["template_id"] == "top_sleeveless"
    assert outfit_13_top["facets"]["garment_class"]["source"] == "user_override"
    assert outfit_13_top["facets"]["sleeve_length"]["value"] == "sleeveless"
    assert outfit_13_top["facets"]["colors"]["value"] == "pastel pink"
    assert outfit_13_top["facets"]["colors"]["source"] == "user_confirmed"
    assert outfit_13_top["display_name"] == "pastel pink sleeveless top"
    assert "sleeveless" in outfit_13_top["tags"]
    assert "top_sleeveless" in outfit_13_top["tags"]
    assert "pastel pink" in outfit_13_top["tags"]
    assert "dusty rose" not in outfit_13_top["tags"]
    assert outfit_13_top["images"]["output_512"]["path"] == "outfit_13/top/output.png"
    assert outfit_13_top["images"]["output_1k"]["path"] == "outfit_13/top/output_1k.png"
    assert (
        outfit_13_top["images"]["output_512"]["sha256"]
        == "1580b39245e2bc3fc6fd2ac7b8f98c22b8f3d300a652fba1aa07bc3e280f747e"
    )
    assert outfit_13_top["user_override"] is not None

    outfit_7_top = by_id["outfit_7_top"]
    assert outfit_7_top["display_category"] == "top"
    assert outfit_7_top["display_name"] == "floral sleeveless top"
    assert outfit_7_top["template"]["template_id"] == "top_sleeveless"
    assert outfit_7_top["facets"]["garment_class"]["source"] == "user_override"
    assert outfit_7_top["facets"]["sleeve_length"]["value"] == "sleeveless"
    assert outfit_7_top["facets"]["colors"]["value"] is None
    assert "beige" not in outfit_7_top["tags"]
    assert "sleeveless" in outfit_7_top["tags"]
    assert "floral" in outfit_7_top["tags"]
    assert outfit_7_top["user_override"] is not None
    assert outfit_7_top["images"]["output_512"]["path"] == "outfit_7/top/output.png"
    assert (
        outfit_7_top["images"]["output_512"]["sha256"]
        == "a9745e7c269372172ae35cac4504e1cea93a356ffe0835f6b7b6d3806348a6ab"
    )
    assert (
        outfit_7_top["images"]["output_512"]["sha256"]
        != "2ffe7dbcffc65c993ce71a2a27f80095e536c358badc87a807f579e241e23ee2"
    )

    outfit_9_top = by_id["outfit_9_top"]
    assert outfit_9_top["template"]["template_id"] == "top_sleeveless"
    assert outfit_9_top["facets"]["sleeve_length"]["value"] == "sleeveless"
    assert outfit_9_top["user_override"] is not None
    assert "sleeveless" in outfit_9_top["tags"]
    assert outfit_9_top["display_name"] == "black sleeveless top"
    outfit_9_hits = search_catalog(payload=index_payload, query="outfit_9", role="top")
    assert outfit_9_hits[0].catalog_id == "outfit_9_top"
    assert outfit_9_hits[0].display_name == "black sleeveless top"
    black_blouse_hits = search_catalog(payload=index_payload, query="black blouse", role="top")
    assert black_blouse_hits[0].catalog_id == "outfit_11_top"
    assert black_blouse_hits[0].display_name == "black blouse"
    assert outfit_9_top["catalog_id"] != black_blouse_hits[0].catalog_id

    outfit_6_bottom = by_id["outfit_6_bottom"]
    assert outfit_6_bottom["garment_class_normalized"] == "skirt"
    assert outfit_6_bottom["garment_subtype"] == "pencil"
    assert outfit_6_bottom["garment_id"] == "garment_black_pencil_skirt_001"
    assert "outfit_26_bottom" in outfit_6_bottom["observation_ids"]

    assert "outfit_2_top" not in by_id
    assert "outfit_19_top" not in by_id
    assert "outfit_27_dress" not in by_id
    assert "outfit_31_bottom" not in by_id
    assert "outfit_2_bottom" in by_id
    assert "outfit_31_top" in by_id

    index_summary = index_payload["summary"]
    assert index_summary["role_counts"]["top"] == 24
    assert index_summary["role_counts"]["dress"] == 2
    assert index_summary["role_counts"]["bottom"] == 7
    assert index_summary["display_category_counts"]["top"] == 22
    assert index_summary["display_category_counts"]["blazer"] == 2
    assert index_summary["display_category_counts"]["dress"] == 2
    assert index_summary["display_category_counts"]["bottom"] == 7
    assert set(index_summary["display_sections"]["blazer"]) == {"outfit_3_top", "outfit_4_top"}
    assert "outfit_19_top" not in index_summary["display_sections"].get("blazer", [])
    assert "outfit_27_dress" not in index_summary["sections"].get("dress", [])
    assert "outfit_29_dress" in index_summary["sections"]["dress"]
    assert "outfit_30_dress" in index_summary["sections"]["dress"]

    outfit_29_dress = by_id["outfit_29_dress"]
    assert outfit_29_dress["role"] == "dress"
    assert outfit_29_dress["template"]["template_id"] == "dress_knee_length_full_sleeve"
    assert "lace" in " ".join(outfit_29_dress["tags"]).lower()
    assert outfit_29_dress["facets"]["colors"]["value"] == "pastel pink"
    assert outfit_29_dress["facets"]["colors"]["source"] == "user_confirmed"
    assert "dusty rose" not in outfit_29_dress["tags"]

    outfit_30_dress = by_id["outfit_30_dress"]
    assert outfit_30_dress["role"] == "dress"
    assert outfit_30_dress["template"]["template_id"] == "dress_knee_length_full_sleeve"
    assert "full sleeve" in " ".join(outfit_30_dress["tags"]).lower()
    assert outfit_30_dress["facets"]["colors"]["value"] == "forest green"
    assert outfit_30_dress["facets"]["colors"]["source"] == "user_confirmed"
    assert "black" not in outfit_30_dress["tags"]
    assert "dark green" not in outfit_30_dress["tags"]

    outfit_31_top = by_id["outfit_31_top"]
    assert outfit_31_top["template"]["template_id"] == "top_full_sleeve"
    assert "black" in outfit_31_top["tags"]

    dry_outfit_29_dress = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_29",
        role="dress",
        dry_run=True,
    )
    assert dry_outfit_29_dress.status == "dry_run"
    assert dry_outfit_29_dress.generation_calls == 0
    assert dry_outfit_29_dress.plan.reuse_status == "reuse_production"

    dry_outfit_27_dress = run_pipeline_case(
        repo_root=cloth_repo,
        fixture_id="outfit_27",
        role="dress",
        dry_run=True,
    )
    assert dry_outfit_27_dress.status == "dry_run"
    assert dry_outfit_27_dress.generation_calls == 0
    assert dry_outfit_27_dress.plan.reuse_status == "reuse_production"

    with pytest.raises(CatalogPipelineError, match="no manifest case for outfit_27/top"):
        build_pipeline_plan(repo_root=cloth_repo, fixture_id="outfit_27", role="top")

    outfit_28_bottom = by_id["outfit_28_bottom"]
    assert outfit_28_bottom["garment_subtype"] == "long"
    assert "maxi" in outfit_28_bottom["tags"] or "long skirt" in outfit_28_bottom["tags"]

    red_shirt_hits = search_catalog(payload=index_payload, query="red satin shirt")
    assert red_shirt_hits[0].catalog_id == "outfit_6_top"
    blazer_hits = search_catalog(payload=index_payload, query="black blazer")
    assert blazer_hits[0].catalog_id == "outfit_3_top"
    waistcoat_hits = search_catalog(payload=index_payload, query="closed waistcoat")
    assert waistcoat_hits[0].catalog_id == "outfit_10_top"
    black_vest_hits = search_catalog(payload=index_payload, query="black vest")
    assert black_vest_hits[0].catalog_id == "outfit_10_top"
    skirt_hits = search_catalog(payload=index_payload, query="pencil skirt")
    assert skirt_hits[0].catalog_id == "outfit_6_bottom"
    knee_dress_hits = search_catalog(payload=index_payload, query="knee length dress")
    assert knee_dress_hits[0].catalog_id == "outfit_29_dress"
    short_sleeve_dress_hits = search_catalog(payload=index_payload, query="short sleeve dress")
    assert short_sleeve_dress_hits[0].catalog_id == "outfit_29_dress"
    outfit_27_dress_hits = search_catalog(payload=index_payload, query="outfit 27 dress")
    assert outfit_27_dress_hits == []
    outfit_27_legacy_hits = search_catalog(payload=index_payload, query="outfit 27 top")
    assert outfit_27_legacy_hits == []
    dress_role_hits = search_catalog(payload=index_payload, query="", role="dress")
    assert {hit.catalog_id for hit in dress_role_hits} == {
        "outfit_29_dress",
        "outfit_30_dress",
    }
    lace_dress_hits = search_catalog(payload=index_payload, query="lace dress")
    assert lace_dress_hits[0].catalog_id == "outfit_29_dress"
    pastel_pink_dress_hits = search_catalog(payload=index_payload, query="pastel pink dress")
    assert pastel_pink_dress_hits[0].catalog_id == "outfit_29_dress"
    forest_green_dress_hits = search_catalog(payload=index_payload, query="forest green dress")
    assert forest_green_dress_hits[0].catalog_id == "outfit_30_dress"
    forest_green_bodycon_hits = search_catalog(
        payload=index_payload, query="forest green bodycon dress"
    )
    assert forest_green_bodycon_hits[0].catalog_id == "outfit_30_dress"
    full_sleeve_dress_hits = search_catalog(payload=index_payload, query="full sleeve dress")
    assert full_sleeve_dress_hits[0].catalog_id in {"outfit_29_dress", "outfit_30_dress"}
    turtleneck_hits = search_catalog(payload=index_payload, query="black turtleneck top")
    assert turtleneck_hits[0].catalog_id == "outfit_31_top"
    ribbed_pants_hits = search_catalog(payload=index_payload, query="drawstring")
    assert ribbed_pants_hits == []
    long_skirt_hits = search_catalog(payload=index_payload, query="maxi skirt")
    assert long_skirt_hits[0].catalog_id == "outfit_28_bottom"
    shared_skirt_hits = search_catalog(payload=index_payload, query="outfit 26 bottom")
    assert shared_skirt_hits[0].catalog_id == "outfit_6_bottom"

    beige_hits = search_catalog(payload=index_payload, query="beige printed blouse")
    for hit in beige_hits:
        if hit.catalog_id == "outfit_7_top":
            assert "beige" not in hit.matched_tokens
    beige_only_hits = search_catalog(payload=index_payload, query="beige", role="top")
    assert all(hit.catalog_id != "outfit_7_top" for hit in beige_only_hits)
    floral_hits = search_catalog(payload=index_payload, query="floral", role="top")
    assert floral_hits[0].catalog_id == "outfit_7_top"
    floral_sleeveless_hits = search_catalog(
        payload=index_payload, query="floral sleeveless", role="top"
    )
    assert floral_sleeveless_hits[0].catalog_id == "outfit_7_top"
    navy_hits = search_catalog(payload=index_payload, query="navy blue office blouse collar")
    assert navy_hits[0].catalog_id != "outfit_8_top"
    zip_hits = search_catalog(payload=index_payload, query="navy zip top")
    assert zip_hits[0].catalog_id == "outfit_8_top"
    zip_v_hits = search_catalog(payload=index_payload, query="blue zipper V-neck top")
    assert zip_v_hits[0].catalog_id == "outfit_8_top"
    pink_hits = search_catalog(payload=index_payload, query="pink office blouse")
    assert pink_hits[0].catalog_id == "outfit_12_top"

    pastel_pink_top_hits = search_catalog(payload=index_payload, query="pastel pink sleeveless top")
    assert pastel_pink_top_hits[0].catalog_id == "outfit_13_top"
    pastel_pink_lace_hits = search_catalog(
        payload=index_payload, query="pastel pink lace halter top"
    )
    assert pastel_pink_lace_hits[0].catalog_id == "outfit_13_top"
    dusty_rose_only_hits = search_catalog(payload=index_payload, query="dusty rose")
    assert all(hit.catalog_id != "outfit_13_top" for hit in dusty_rose_only_hits)
    dusty_rose_top_hits = search_catalog(payload=index_payload, query="dusty rose sleeveless top")
    outfit_13_dusty_hits = [h for h in dusty_rose_top_hits if h.catalog_id == "outfit_13_top"]
    for hit in outfit_13_dusty_hits:
        assert "dusty" not in hit.matched_tokens
        assert "rose" not in hit.matched_tokens
    green_blouse_hits = search_catalog(payload=index_payload, query="green office blouse")
    assert green_blouse_hits[0].catalog_id == "outfit_14_top"
    lemon_hits = search_catalog(payload=index_payload, query="lemon print sleeveless blouse")
    assert lemon_hits[0].catalog_id == "outfit_18_top"
    large_collar_hits = search_catalog(payload=index_payload, query="sleeveless large collar top")
    assert large_collar_hits[0].catalog_id == "outfit_18_top"
    lemon_collar_hits = search_catalog(payload=index_payload, query="lemon print collar blouse")
    assert lemon_collar_hits[0].catalog_id == "outfit_18_top"
    white_shirt_hits = search_catalog(payload=index_payload, query="white button-down shirt")
    assert white_shirt_hits[0].catalog_id == "outfit_22_top"
    outfit_22_hits = search_catalog(payload=index_payload, query="outfit_22", role="top")
    assert outfit_22_hits[0].catalog_id == "outfit_22_top"
    green_blazer_hits = search_catalog(payload=index_payload, query="green checkered blazer")
    assert "outfit_19_top" not in {hit.catalog_id for hit in green_blazer_hits}
    pink_floral_hits = search_catalog(payload=index_payload, query="pink floral print")
    assert "outfit_2_top" not in {hit.catalog_id for hit in pink_floral_hits}
    lavender_hits = search_catalog(payload=index_payload, query="lavender peplum blouse")
    assert lavender_hits[0].catalog_id == "outfit_21_top"
    navy_short_hits = search_catalog(payload=index_payload, query="navy short sleeve blouse")
    assert navy_short_hits[0].catalog_id == "outfit_24_top"

    khaki_hits = search_catalog(payload=index_payload, query="khaki trousers")
    tan_hits = search_catalog(payload=index_payload, query="tan trousers")
    brown_pair_hits = search_catalog(payload=index_payload, query="outfit 8 bottom")
    gray_pair_hits = search_catalog(payload=index_payload, query="outfit 12 bottom")
    dark_gray_pair_hits = search_catalog(payload=index_payload, query="outfit 3 bottom")
    for hits, canonical_id in (
        (khaki_hits, "outfit_24_bottom"),
        (tan_hits, "outfit_2_bottom"),
        (brown_pair_hits, "outfit_2_bottom"),
        (gray_pair_hits, "outfit_10_bottom"),
        (dark_gray_pair_hits, "outfit_15_bottom"),
    ):
        assert hits[0].catalog_id == canonical_id

    relaxed_trouser_hits = search_catalog(payload=index_payload, query="relaxed fit trousers")
    assert relaxed_trouser_hits[0].catalog_id == "outfit_22_bottom"
    white_relaxed_hits = search_catalog(payload=index_payload, query="white relaxed-fit trousers")
    assert white_relaxed_hits[0].catalog_id == "outfit_22_bottom"
    outfit_17_bottom_hits = search_catalog(payload=index_payload, query="outfit 17 bottom")
    assert outfit_17_bottom_hits[0].catalog_id == "outfit_22_bottom"
    outfit_5_bottom_hits = search_catalog(payload=index_payload, query="outfit 5 bottom")
    assert outfit_5_bottom_hits[0].catalog_id == "outfit_22_bottom"
    outfit_19_bottom_hits = search_catalog(payload=index_payload, query="outfit 19 bottom")
    assert outfit_19_bottom_hits[0].catalog_id == "outfit_22_bottom"
    slim_trouser_hits = search_catalog(payload=index_payload, query="slim fit trousers")
    assert slim_trouser_hits[0].catalog_id == "outfit_15_bottom"
    straight_khaki_hits = search_catalog(payload=index_payload, query="straight-fit khaki trousers")
    assert straight_khaki_hits[0].catalog_id == "outfit_24_bottom"
    straight_fit_hits = search_catalog(payload=index_payload, query="straight fit trousers")
    assert straight_fit_hits[0].catalog_id in {
        "outfit_2_bottom",
        "outfit_24_bottom",
    }

    filtered_bottoms = search_catalog(
        payload=index_payload,
        query="pants",
        role="bottom",
    )
    assert all(hit.catalog_id.endswith("_bottom") for hit in filtered_bottoms)
    assert filtered_bottoms[0].catalog_id < filtered_bottoms[-1].catalog_id

    tied = search_catalog(payload=index_payload, query="")
    assert [hit.catalog_id for hit in tied] == sorted(
        item["catalog_id"] for item in index_payload["items"]
    )

    final_manifest = json.loads((final_root / "manifest.json").read_text(encoding="utf-8"))
    identity_block = final_manifest.get("garment_identities")
    if identity_block:
        assert identity_block["observation_count"] == EXPECTED_OBSERVATION_COUNT
        assert identity_block["unique_garment_count"] == EXPECTED_UNIQUE_GARMENT_COUNT
        assert identity_block["catalog_item_count"] == EXPECTED_ITEM_COUNT
        assert len(identity_block["groups"]) == 7
        assert (
            identity_block["observation_to_garment"]["outfit_26_bottom"]
            == "garment_black_pencil_skirt_001"
        )
        assert (
            identity_block["observation_to_garment"]["outfit_20_top"]
            == "garment_white_button_down_shirt_001"
        )
        assert (
            identity_block["observation_to_garment"]["outfit_25_bottom"]
            == "garment_khaki_slim_trousers_001"
        )
        assert (
            identity_block["observation_to_garment"]["outfit_1_bottom"]
            == "garment_tan_trousers_001"
        )
        assert (
            identity_block["observation_to_garment"]["outfit_8_bottom"]
            == "garment_tan_trousers_001"
        )
        assert (
            identity_block["observation_to_garment"]["outfit_3_bottom"]
            == "garment_gray_trousers_002"
        )
        assert (
            identity_block["observation_to_garment"]["outfit_4_bottom"]
            == "garment_gray_trousers_002"
        )
    contact_sheets = final_manifest["contact_sheets"]
    assert contact_sheets["batch_size_outfits"] == 4
    assert contact_sheets["directory"] == "final_catalog/contact_sheets"
    assert len(contact_sheets["sheets"]) == 8
    assert not (final_root / "contact_sheet.jpg").is_file()
    sheet_names = [sheet["filename"] for sheet in contact_sheets["sheets"]]
    assert sheet_names == [
        "outfits_01-04.jpg",
        "outfits_05-08.jpg",
        "outfits_09-12.jpg",
        "outfits_13-16.jpg",
        "outfits_17-20.jpg",
        "outfits_21-24.jpg",
        "outfits_25-28.jpg",
        "outfits_29-31.jpg",
    ]
    covered_outfits = [outfit for sheet in contact_sheets["sheets"] for outfit in sheet["outfits"]]
    assert covered_outfits == [f"outfit_{index}" for index in range(1, 32)]
    assert sum(sheet["case_count"] for sheet in contact_sheets["sheets"]) == 59
    final_batch = contact_sheets["sheets"][-1]
    assert final_batch["outfits"] == ["outfit_29", "outfit_30", "outfit_31"]
    assert final_batch["outfit_range"] == {"start": 29, "end": 31}
    assert final_batch["case_count"] == 4
    for sheet in contact_sheets["sheets"]:
        assert (final_root / "contact_sheets" / sheet["filename"]).is_file()
        assert len(sheet["sha256"]) == 64

    catalog_json = final_root / "catalog.json"
    if catalog_json.is_file():
        write_catalog_index(
            repo_root=cloth_repo,
            final_root=final_root,
            output_path=catalog_json,
        )
        on_disk = catalog_json.read_bytes()
        assert on_disk == first_serialized.encode("utf-8")
        second_write = catalog_json.read_bytes()
        write_catalog_index(
            repo_root=cloth_repo,
            final_root=final_root,
            output_path=catalog_json,
        )
        assert catalog_json.read_bytes() == second_write
        identities_json = final_root / "garment_identities.json"
        assert identities_json.is_file()


def test_texture_qc_and_derived_geometry_invariants() -> None:
    """Texture/color QC heuristics and derived geometry validation."""
    identical = Image.new("RGB", (512, 512), (200, 40, 60))
    for x in range(120, 380):
        for y in range(80, 420):
            identical.putpixel((x, y), (200, 40, 60))
    low_shift = compare_texture_heuristic(
        source_image=identical,
        output_image=identical,
        role="top",
    )
    assert low_shift.heuristic is True
    assert low_shift.mean_delta_e == 0.0
    assert low_shift.flags == ()

    source = Image.new("RGB", (512, 512), (255, 255, 255))
    output = Image.new("RGB", (512, 512), (255, 255, 255))
    for x in range(100, 400):
        for y in range(100, 400):
            source.putpixel((x, y), (20, 180, 40))
            output.putpixel((x, y), (220, 20, 200))
    high_shift = compare_texture_heuristic(source_image=source, output_image=output, role="top")
    assert "high_mean_color_shift" in high_shift.flags

    repo_root = Path(__file__).resolve().parents[1]
    pants = render_template_png(TEMPLATE_BY_ID["pants"])
    assert pants_centerline_gap_rows(pants) > 0

    outfit_4_final = repo_root / (
        "bench/catalog_generation/outputs/nano_banana_2/catalog_production_v1/outfit_4/top.png"
    )
    if outfit_4_final.is_file():
        silhouette = extract_neutral_geometry_silhouette(outfit_4_final)
        validation = validate_derived_geometry_image(silhouette)
        assert validation["width_metrics"]["bbox_width_fraction"] > 0.5
        assert silhouette.getpixel((0, 0)) == WHITE_BACKGROUND
