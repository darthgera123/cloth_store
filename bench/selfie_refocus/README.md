# Selfie refocus (bench + final deliverable)

Deterministic mirror-selfie portrait crops with **blur-only** background refocus
(``refocus_method: blur_only_v2``). Background color and brightness are preserved;
only spatial blur is applied behind the feathered person mask.

## Processing flow

1. **Garment-union bbox** — expand Plan1 localization boxes with head/side/feet padding.
2. **SAM person mask** — segment reflected person inside padded crop.
3. **Quality validation** — reject torso-only masks, incomplete garment coverage, or
   insufficient vertical extent.
4. **Qwen full-person recovery** (when needed) — localize full reflected person,
   merge with garment union, re-segment; writes ``recovery_diagnostic_sheet.jpg``.
5. **Aspect-safe portrait crop** — prefer 4:5, fallback 3:4 or source aspect.
6. **Blur-only refocus** — Gaussian blur on background; person core pixels unchanged.
7. **Review assessment** — metrics gate ``crop_refocused`` vs fallback ``crop_only``.
8. **Packaging** — copy variants to ``final_selfies/`` and render 4-outfit contact sheets.

Does **not** modify source photos or production catalog outputs.

## Bench workspace

Under `bench/selfie_refocus/candidates/<fixture_id>/`:

| Artifact | Description |
|----------|-------------|
| `crop_only.jpg` | Portrait crop, no background treatment |
| `crop_refocused.jpg` | Portrait crop with blur-only background refocus |
| `person_mask.png` | SAM person mask (reused when hashes match) |
| `bbox_mask_overlay.jpg` | Source with bbox + mask overlay |
| `comparison_sheet.jpg` | Four-panel review sheet |
| `metadata.json` | Crop geometry, metrics, `refocus_method: blur_only_v2` |

### Neck-down privacy variant (optional)

Deterministic, non-generative privacy crops sub-crop the approved selfie variant
(``crop_refocused`` or review fallback ``crop_only``) below an explicit
``face_bottom_cutoff``. Reviewed per-fixture overrides live in
``privacy_cutoff_overrides.json``.

| Artifact | Description |
|----------|-------------|
| `crop_neck_down.jpg` | Neck-down privacy variant |
| `crop_neck_down.metadata.json` | Cutoff provenance, geometry, QC |

Batch (fixtures 1–31):

```bash
uv run cloth-store-selfie-privacy-crop --repo-root . --from-fixture 1 --to-fixture 31
uv run cloth-store-selfie-privacy-crop --repo-root . --validate-only
uv run cloth-store-selfie-privacy-crop --repo-root . --bench-only --fixture outfit_1
```

Packaging copies ``crop_neck_down.jpg`` into ``final_selfies/outfit_N/`` and updates
``manifest.json`` with an optional ``privacy`` block. Does **not** replace
``crop_refocused.jpg`` / ``crop_only.jpg`` or modify website payloads.

Privacy contact sheets: ``final_selfies/contact_sheets_privacy/`` (4-outfit batches).
Aggregate QC: ``final_selfies/privacy_qc_report.json``.

Implemented in `src/cloth_store/selfie_privacy_crop.py` and
`src/cloth_store/selfie_privacy_packaging.py`. The crop anchors at
``face_bottom_cutoff`` (just below the jaw) rather than the over-conservative
``collarbone_cutoff_reference`` recorded in metadata for comparison. Source
variant defaults to ``final_selfies/<fixture>/crop_refocused.jpg`` when present.
Does not overwrite `crop_refocused.jpg`, modify `final_selfies/`, or call
generative APIs.

## Final deliverable

Packaged review bundle under `final_selfies/` (manifest, per-fixture variants, 4-outfit contact sheets).

## Run (fixtures 1–31)

```bash
bench/selfie_refocus/run.sh --from-fixture 1 --to-fixture 31
```

Idempotent rerun skips fixtures whose `blur_only_v2` outputs match current source/localization hashes.

Validate only:

```bash
bench/selfie_refocus/run.sh --validate-only --from-fixture 1 --to-fixture 31
```

Bench only (no packaging):

```bash
bench/selfie_refocus/run.sh --bench-only --from-fixture 3 --to-fixture 10
```

Or directly:

```bash
uv run cloth-store-selfie-refocus --from-fixture 1 --to-fixture 31
uv run cloth-store-selfie-final-packaging --from-fixture 1 --to-fixture 31
uv run cloth-store-selfie-final-packaging --validate-only
```

## Review policy

Fixtures marked `review_required: true` in metadata/manifest should use `crop_only` until manually corrected. Triggers: low bbox confidence, subject clipped at crop edge, edge halo > 0.08, low mask coverage, or person preservation < 0.98.

## Parameters (`metadata.json`)

- `refocus_method`: `blur_only_v2` (canonical; blur-only, no dimming or desaturation)
- `blur_radius_px`: 8
- `feather_radius_px`: 5
- `background_brightness` / `background_saturation`: always `1.0` (schema compatibility; blur-only preserves originals)
