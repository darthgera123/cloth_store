# Manual garment identity registry

User-confirmed physical-garment overlaps are declared in
`bench/catalog_generation/garment_identities.json`. The catalog index deduplicates
retrieval items from this registry; it does **not** auto-merge from similarity,
hashes, or VLM output.

Durable **role-level exclusions** live separately in
`bench/catalog_generation/catalog_exclusions.json` (see
[Catalog exclusions](#catalog-exclusions) below).

## Current corrected identities (Aug 2026)

Each group lists observations of the **same physical garment**. The
**canonical observation** supplies the indexed catalog card, 512px image, and
display facets; aliases remain in `source_observations` for provenance only.

| Garment ID | Canonical | Observations | Normalized label |
|------------|-----------|--------------|------------------|
| `garment_gray_trousers_002` | `outfit_15/bottom` | 3, 4, 15, 16 | slim fit gray trousers |
| `garment_gray_trousers_001` | `outfit_10/bottom` | 10–14 | gray trousers |
| `garment_off_white_trousers_001` | `outfit_22/bottom` | 5, 17–22 | white relaxed-fit trousers |
| `garment_tan_trousers_001` | `outfit_2/bottom` | 1, 2, 7, 8, 9 | tan straight-fit trousers |
| `garment_khaki_slim_trousers_001` | `outfit_24/bottom` | 23–25 | straight-fit khaki trousers |
| `garment_black_pencil_skirt_001` | `outfit_6/bottom` | 6, 26 | black pencil skirt |
| `garment_white_button_down_shirt_001` | `outfit_22/top` | 16, 20, 22 | white long-sleeve button-down shirt |

**Color normalization notes:**

- Tan group: stale VLM labels `brown` / `taupe` are observation noise; indexed
  color is `tan`, fit is `straight`.
- Khaki group: kept distinct from tan; stale `tan` / `brown` tags are suppressed
  on the canonical item so `"khaki trousers"` search does not resolve to tan.
- White and gray groups: stale off-white / beige / dark-gray tokens are similarly
  suppressed via `stale_color_tags` in `facet_corrections`.

Choose canonical observations from **best approved output / QC**, not fixture
order. Record rationale in `canonical_selection_reason`.

## Catalog exclusions

Excluded observations remain in `final_catalog/` packaging and contact sheets for
review history, but are **omitted from `catalog.json` indexing** and the
storefront. Retained counterpart garments on the same fixture stay indexed; their
fixture selfies remain usable in styling.

| Observation | Reason |
|-------------|--------|
| `outfit_31/bottom` | Discarded brown drawstring trousers (`outfit_31/top` retained) |
| `outfit_27/dress` | Discarded knee-length polo dress |
| `outfit_19/top` | Discarded green checkered blazer (`outfit_19/bottom` → white trousers via `outfit_22/bottom`) |
| `outfit_2/top` | Discarded pink floral blouse (`outfit_2/bottom` → tan trousers) |

## Blazers display category

`outfit_3/top` and `outfit_4/top` are indexed with `role=top` (for pairing and
styling) but appear under the **Blazers** storefront section when
`garment_class_normalized == "blazer"`. `outfit_19/top` remains excluded.

## Current generated counts

Verify from rebuilt artifacts (do not hard-code in application logic except
test/constants guards):

```bash
uv run cloth-store-catalog-index --repo-root . --validate-only
```

Expected after a full curation rebuild:

| Metric | Count |
|--------|------:|
| Manifest observations | 59 |
| Logical garments (identity-resolved) | 37 |
| Indexed catalog items | 33 |
| Excluded observations | 4 |
| Identity merge groups | 7 |
| Indexed bottoms | 7 |
| Display: tops | 22 |
| Display: blazers | 2 |
| Display: dresses | 2 |
| Display: bottoms | 7 |
| Wearable `role=top` (includes blazers) | 24 |

Source of truth: `final_catalog/catalog.json` → `summary`.

## Source-of-truth files

| File | Role |
|------|------|
| `bench/catalog_generation/garment_identities.json` | Durable identity groups + observation enrichments |
| `bench/catalog_generation/catalog_exclusions.json` | Durable role-level exclusions |
| `final_catalog/manifest.json` | Packaged observation inventory (59 cases) |
| `final_catalog/garment_identities.json` | Derived identity snapshot (written by rebuild) |
| `final_catalog/catalog.json` | Derived lexical index + summary counts |
| `final_catalog/storefront.json` | Derived storefront payload |

Curation-only edits touch the **bench** JSON registries first, then rebuild
derived `final_catalog/` outputs. No model or API calls are required unless you
are regenerating catalog images or refocus selfies.

## Curation-only rebuild chain

After editing `garment_identities.json` and/or `catalog_exclusions.json`:

```bash
uv run cloth-store-catalog-identities validate --repo-root .
uv run cloth-store-catalog-identities rebuild --repo-root . --annotate-manifest
uv run cloth-store-catalog-exclusions --repo-root .
uv run cloth-store-catalog-index --repo-root .
uv run cloth-store-web-build --repo-root .
uv run cloth-store-catalog-index --repo-root . --validate-only
```

This chain is deterministic: it copies existing PNG bytes, rewrites metadata
facets/tags/search text, and refreshes manifest annotations. It does **not**
invoke Gemini or regenerate images.

Re-run `uv run cloth-store-catalog-final-packaging --repo-root .` only when
contact-sheet identity labels or per-case PNG copies must refresh after **new**
production generations.

## Add another confirmed overlap group

1. Inspect both outfit observations in `final_catalog/` contact sheets and outputs.
2. Choose a **canonical observation** — prefer the best approved output/QC, not fixture
   order. Record the rationale in `canonical_selection_reason`.
3. Append a new group to `garment_identities.json`:

```json
{
  "garment_id": "garment_<descriptive_slug>_NNN",
  "canonical_observation_id": "outfit_12_bottom",
  "observation_ids": ["outfit_11_bottom", "outfit_12_bottom"],
  "reason": "user_confirmed",
  "canonical_selection_reason": "Why this observation is canonical (QC/output approval).",
  "display_name": "optional normalized label",
  "facet_corrections": {
    "colors": ["primary"],
    "fit": "relaxed",
    "stale_color_tags": ["alias", "tokens"]
  },
  "notes": "Same physical garment worn in outfits X and Y."
}
```

For standalone observations that are not merged into a group, append an
`observation_enrichments` entry instead:

```json
{
  "observation_id": "outfit_1_bottom",
  "reason": "user_confirmed",
  "facet_corrections": {
    "fit": "straight"
  },
  "notes": "User-confirmed straight-fit trousers."
}
```

Do not use observation enrichments on observations already listed in a
`groups` entry; apply fit and color corrections through the group's
`facet_corrections` instead.

4. Run the [curation-only rebuild chain](#curation-only-rebuild-chain) above.

5. Update `EXPECTED_UNIQUE_GARMENT_COUNT` in
   `src/cloth_store/catalog_garment_identities.py` and
   `EXPECTED_CATALOG_ITEM_COUNT` in `src/cloth_store/catalog_exclusions.py`
   to match the rebuilt `catalog.json` summary, then re-run tests.

## Rules enforced at validate/index time

- Every `observation_id` must exist in `final_catalog/manifest.json`.
- Each observation appears in at most one group; unlisted observations default to
  `garment_id == observation_id`.
- `canonical_observation_id` must be listed in `observation_ids`.
- All observations in a group share the same role and compatible garment class.
- Unknown observation IDs fail validation.
- Excluded observations must not appear as indexed catalog items.
