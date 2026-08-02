# Final selfies (blur-only refocus)

Self-contained mirror-selfie portrait crops with blur-only background refocus for review.
Source photos under `data/` are never modified.

## Layout

```
final_selfies/
  manifest.json
  README.md
  contact_sheets/
    - `final_selfies/contact_sheets/outfits_01-04.jpg` (1–4)
    - `final_selfies/contact_sheets/outfits_05-08.jpg` (5–8)
    - `final_selfies/contact_sheets/outfits_09-12.jpg` (9–12)
    - `final_selfies/contact_sheets/outfits_13-16.jpg` (13–16)
    - `final_selfies/contact_sheets/outfits_17-20.jpg` (17–20)
    - `final_selfies/contact_sheets/outfits_21-24.jpg` (21–24)
    - `final_selfies/contact_sheets/outfits_25-28.jpg` (25–28)
    - `final_selfies/contact_sheets/outfits_29-31.jpg` (29–31)
  outfit_N/
    crop_only.jpg
    crop_refocused.jpg
    metadata.json
```

Person masks and bench overlays remain under `bench/selfie_refocus/candidates/` and are
referenced from each fixture's `bench_artifacts` block.

## Regenerate

```bash
bench/selfie_refocus/run.sh --from-fixture 1 --to-fixture 31
uv run cloth-store-selfie-final-packaging --repo-root . --from-fixture 1 --to-fixture 31
uv run cloth-store-selfie-final-packaging --repo-root . --validate-only
```

## Review policy

Fixtures marked `review_required: true` should use `crop_only` until manually corrected.
Blur-only refocus preserves background color and brightness (`refocus_method: blur_only_v2`).
