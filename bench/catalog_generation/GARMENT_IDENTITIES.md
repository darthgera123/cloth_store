# Manual garment identity registry

User-confirmed physical-garment overlaps are declared in
`bench/catalog_generation/garment_identities.json`. The catalog index deduplicates
retrieval items from this registry; it does **not** auto-merge from similarity,
hashes, or VLM output.

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
    "colors": ["primary", "alias", "tokens"],
    "fit": "relaxed"
  },
  "notes": "Same physical white relaxed-fit trousers worn in outfits 17, 18, 19, 20, and 21."
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

4. Validate and rebuild:

```bash
uv run cloth-store-catalog-identities validate --repo-root .
uv run cloth-store-catalog-index --repo-root .
```

5. Re-run packaging only if contact-sheet identity labels or manifest annotations must
   refresh (`uv run cloth-store-catalog-final-packaging --repo-root .`). This copies PNG
   bytes only; it does not regenerate catalog images.

## Rules enforced at validate/index time

- Every `observation_id` must exist in `final_catalog/manifest.json`.
- Each observation appears in at most one group; unlisted observations default to
  `garment_id == observation_id`.
- `canonical_observation_id` must be listed in `observation_ids`.
- All observations in a group share the same role and compatible garment class.
- Unknown observation IDs fail validation.
