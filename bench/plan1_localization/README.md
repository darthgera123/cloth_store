# Plan 1: Localization smoke bench

Runnable Qwen3.5-9B bounding-box and SAM 3.1 mask smoke bench for the six local mirror-selfie fixtures. Active taxonomy: `separates` = top + bottom; `dress` = dress. Shoes were tried early (tight bbox + `shoe_point` + SAM point prompt) and removed from scope due to poor visibility/quality.

## Experiment history

| Stage | Status | Notes |
|-------|--------|-------|
| Qwen3.5-9B bboxes | Done | Apparel-only JSON for all six fixtures |
| Full-image SAM 2.1 | Superseded | Initial masks before crop-based prompting |
| Padded-crop SAM 2.1 | Superseded | 10% bbox pad, role crops |
| SAM 3.1 (gated access) | Done | Current mask backend (`facebook/sam3.1`) |
| Shoe bbox + point SAM | Removed | Dual-box retries, low shoe visibility |
| Crop-based SAM 3.1 apparel | Current | Top/bottom/dress via text + bbox in padded crop |
| Deterministic 512×512 catalogs | Current | Full-foreground union bounds, white RGB, 9% margin |

Known mask/cutout issues (current run):

- **outfit_3 top**: SAM mask has disconnected blazer regions; catalog now uses full foreground union (not largest component).
- **outfit_4 top**: Similar layered blazer; watch for shirt bleed-through.
- **outfit_5/6 bottom**: Wide-leg pants can include mirror frame or floor at hem.
- No `dress` fixture yet; all six are `separates`.

Plan 2 reconstruction models (`bench/plan2_reconstruction/`) have **not** been run.

## Bbox stage

From the repo root inside Apptainer:

```bash
export HF_HOME=/scratch4weeks/pg00807/huggingface
/scratch4weeks/pg00807/bin/uv sync --group dev --group vlm
/scratch4weeks/pg00807/bin/uv run cloth-store-bbox outfit_1.jpeg
./bench/plan1_localization/run.sh
```

Generated JSON is written to `bench/plan1_localization/outputs/` and ignored by Git.

Contract: `{"layout":"separates","top":[...],"bottom":[...]}` or `{"layout":"dress","dress":[...]}`. No shoes or `shoe_point`.

## Mask stage

Pad each validated Qwen bbox by **10% of bbox width/height on each side** (clamped to image bounds), crop the source image to that padded box, then segment inside the crop with official SAM 3.1 (`facebook/sam3.1`, `sam3.1_multiplex.pt`). Top, bottom, and dress use text + bbox prompting only. Crop-local masks are pasted back into full-resolution PNGs with zeros outside the padded crop.

Single fixture:

```bash
export HF_HOME=/scratch4weeks/pg00807/huggingface
/scratch4weeks/pg00807/bin/uv sync --group dev --group sam
/scratch4weeks/pg00807/bin/uv run cloth-store-masks \
  outfit_1.jpeg \
  bench/plan1_localization/outputs/outfit_1.json \
  --output-dir bench/plan1_localization/outputs/masks/outfit_1 \
  --pad-fraction 0.10
```

All six fixtures plus contact sheet:

```bash
./bench/plan1_localization/run_masks.sh
```

Smoke only (`outfit_1`):

```bash
./bench/plan1_localization/run_masks.sh --smoke
```

Outputs (ignored):

- `bench/plan1_localization/outputs/masks/outfit_*/{top,bottom,dress}.png` — binary role masks
- `bench/plan1_localization/outputs/masks/outfit_*/overlay.jpg` — color mask overlay
- `bench/plan1_localization/outputs/masks/contact_sheet.jpg`

## Catalog cutout stage

Deterministic 512×512 **RGB** cutouts on opaque white from existing SAM masks and Qwen role JSON.
Template: bounds of **all** foreground mask pixels (full union), **9% margin** on each side for source
crop and canvas inset, aspect-ratio-preserving scale, centered on a white 512×512 canvas.

Single fixture:

```bash
/scratch4weeks/pg00807/bin/uv sync --group dev
/scratch4weeks/pg00807/bin/uv run cloth-store-cutouts \
  outfit_1.jpeg \
  bench/plan1_localization/outputs/outfit_1.json \
  --mask-dir bench/plan1_localization/outputs/masks/outfit_1 \
  --output-dir bench/plan1_localization/outputs/catalog_cutouts/outfit_1
```

All six fixtures plus contact sheet:

```bash
./bench/plan1_localization/run_cutouts.sh
```

Outputs (ignored):

- `bench/plan1_localization/outputs/catalog_cutouts/outfit_*/catalog_{top,bottom,dress}.png`
- `bench/plan1_localization/outputs/catalog_cutouts/contact_sheet.jpg`

## Gate

- Bbox CLI exits 0 and prints contract-valid JSON for one fixture.
- `./bench/plan1_localization/run.sh` writes six ignored JSON files under `outputs/`.
- Mask CLI writes one binary PNG per detected role plus an overlay for `outfit_1`, then `./bench/plan1_localization/run_masks.sh` completes all six fixtures.
- Cutout CLI writes normalized `catalog_*.png` per role from existing masks, then `./bench/plan1_localization/run_cutouts.sh` completes all six fixtures.
- `pytest tests/test_vlm_bbox.py tests/test_sam_masks.py tests/test_catalog_cutouts.py` passes without loading model weights.
