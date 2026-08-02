# Final catalog (catalog_production_v1)

Self-contained packaging of production catalog inputs and outputs for all 12 outfits
(outfit_1…outfit_12 × top/bottom). Each case directory contains exact byte copies of
model-bound inputs, structured VLM attributes when available, native 1K output, and
the canonical 512 derivative.

## Layout

```
final_catalog/
  README.md
  manifest.json
  catalog.json
  contact_sheets/
    outfits_01-04.jpg
    outfits_05-08.jpg
    outfits_09-12.jpg
  outfit_N/
    top|bottom/
      input_segmented.png
      input_template.png
      input_detail.png    # tops only, when sent to Gemini
      attributes.json     # when VLM extraction exists
      output_1k.png
      output.png
      metadata.json
```

## Contact sheets

Batched review grids (4 outfits per sheet;
top and bottom kept together per outfit):

    - `final_catalog/contact_sheets/outfits_01-04.jpg` (outfits 1–4)
    - `final_catalog/contact_sheets/outfits_05-08.jpg` (outfits 5–8)
    - `final_catalog/contact_sheets/outfits_09-12.jpg` (outfits 9–12)
    - `final_catalog/contact_sheets/outfits_13-16.jpg` (outfits 13–16)
    - `final_catalog/contact_sheets/outfits_17-20.jpg` (outfits 17–20)
    - `final_catalog/contact_sheets/outfits_21-24.jpg` (outfits 21–24)
    - `final_catalog/contact_sheets/outfits_25-28.jpg` (outfits 25–28)
    - `final_catalog/contact_sheets/outfits_29-31.jpg` (outfits 29–31)

## Contract

- **Authoritative source:** segmented cutout (color, material, texture, details).
- **Template:** geometry/silhouette only; never transfers template gray or fabric.
- **Generation:** one native 1K Gemini call per case (`gemini-3.1-flash-image`), then
  deterministic local 512 LANCZOS derivative.
- **Reuse:** exact-hash reuse or reference promotion when artifacts match; no hidden retries.

## Regeneration CLI

Dry-run (validate, zero API calls):

```bash
uv run cloth-store-catalog-pipeline --fixture outfit_1 --role top --dry-run
```

Generate or reuse production outputs:

```bash
uv run cloth-store-catalog-pipeline --fixture outfit_1 --role top
uv run cloth-store-catalog-pipeline --fixture outfit_1 --role top --regenerate  # billable
```

Repackage after production changes:

```bash
uv run cloth-store-catalog-final-packaging --repo-root .
uv run cloth-store-catalog-final-packaging --repo-root . --contact-sheet-batch-size 4
```

## Summary

- Packaged at: `2026-08-02T03:26:33.658104+00:00`
- Cases ok: 59 / 59
- Cases missing/error: 0
- Estimated output cost (new generations): $0.067 per 1K call

## Storefront

The Cloth Store website serves **512px** `output.png` images from this bundle
via `/final_catalog/...`. Rebuild the storefront payload after catalogue changes:

```bash
uv run cloth-store-web-build --repo-root .
```

See [`docs/CLOTH_STORE.md`](../docs/CLOTH_STORE.md) for the full storefront guide.
