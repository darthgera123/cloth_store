# Cloth Store

A private AI-assisted digital wardrobe. The project is implementing
[Phase 1](PHASE_1_CORPUS.md): local garment extraction from mirror selfies.

## Current backend

The FastAPI service provides:

- Health check and source-photo import
- Image validation and orientation-aware dimensions
- Exact duplicate detection with SHA-256
- Perceptual image hashes for future near-duplicate detection
- Idempotent ingestion (201 new / 200 duplicate)
- SQLite and local filesystem storage

Original selfie files are ignored by Git and stored beneath `data/assets`.

## Run locally

```bash
uv sync
uv run cloth-store-api
```

OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

## Verify

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

## Plans

- [Roadmap](ROADMAP.md)
- [Phase 1: Garment extraction](PHASE_1_CORPUS.md)
- [Phase 2: Retrieval and collections](PHASE_2_RETRIEVAL.md)
- [Phase 3: Aesthetic viewer](PHASE_3_VIEWER.md)
