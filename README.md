# Cloth Store

Private AI-assisted digital wardrobe with a production reconstruction pipeline and a static catalogue storefront.

## 1. Reconstruction pipeline

Turn mirror-selfie garment regions into clean, front-facing catalog images. See **[RECONSTRUCTION_PIPELINE.md](RECONSTRUCTION_PIPELINE.md)** for the full flow: VLM bbox → SAM cutouts → structured attributes → template selection → Gemini generation → `final_catalog/` packaging.

```bash
uv sync --group dev --group gemini

# Dry-run (validate + reuse plan, zero API calls)
uv run cloth-store-catalog-pipeline --fixture outfit_6 --role top --dry-run

# Package self-contained review bundle
uv run cloth-store-catalog-final-packaging --repo-root .

# Rebuild lexical index and garment identities
uv run cloth-store-catalog-index --repo-root .
uv run cloth-store-catalog-identities --repo-root .
```

Primary outputs live under `bench/catalog_generation/outputs/nano_banana_2/catalog_production_v1/`; the frozen delivery bundle is `final_catalog/` (manifest, catalog.json, garment_identities.json, per-case assets, contact sheets).

## 2. Website (Lavani's Closet)

Static editorial storefront served from `final_catalog/storefront.json` (derived from catalog.json) plus catalogue images and source selfies.

```bash
uv sync --group dev

# Build or refresh the static storefront bundle
uv run cloth-store-web-build --repo-root .

# Serve locally (stdlib HTTP, no database)
uv run cloth-store-web --repo-root .

# Export a shareable offline bundle (directory + zip)
uv run cloth-store-static-bundle --repo-root . --validate
```

Open **http://127.0.0.1:8080/** — browse, search, top/dress/bottom filters, detail modal with styling selfies, outfit generator, and lucky pairing.

See **[docs/static-bundle-guide.md](docs/static-bundle-guide.md)** for the portable `dist/lavani-closet.zip` snapshot.

## Verify

```bash
uv sync --group dev
uv run ruff format --check .
uv run ruff check .
uv run pytest --collect-only -q   # expect exactly 10 tests
uv run pytest
```

### Test suite policy

The repository caps automated tests at **exactly 10 scenario tests** (`tests/test_scenarios.py`). Each test consolidates related assertions across a major system boundary (static storefront/catalog contract, VLM bbox, SAM/cutouts, templates, Gemini credentials/requests/generation, production pipeline idempotency, texture/QC and derived geometry). Helpers live in `tests/helpers.py` (not collected by pytest).

## Upstream extraction (Apptainer)

Plan 1 localization bench for bbox/mask/cutout generation:

```bash
export HF_HOME=/scratch4weeks/pg00807/huggingface
uv sync --group dev --group vlm --group sam
uv run cloth-store-bbox outfit_1.jpeg
./bench/plan1_localization/run.sh
```

See `bench/plan1_localization/README.md` and `bench/catalog_generation/README.md`.
