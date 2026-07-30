# Phase 1: Garment extraction

## Objective

Accept one mirror selfie at a time, extract individual garments locally, and
persist the minimal output. Original photos stay on the user's machine.

## Scope

Phase 1 is extraction only:

```text
import one image
  -> validate and normalize
  -> detect exact duplicates
  -> extract garment regions
  -> persist source photo + extracted garment assets
```

## Deferred to later phases

Do not design or build these in Phase 1:

- Metadata enrichment and controlled taxonomy
- Image and text embeddings
- Retrieval, recommendations, and collections
- Review UI and approval workflows
- Hosted model calls
- Batch ingestion and background job systems
- PostgreSQL, pgvector, and Alembic migrations

## Current backend

Implemented today:

- FastAPI health and source-photo import endpoints
- Image validation, EXIF normalization, and perceptual hash storage
- Exact-hash idempotency (201 new / 200 duplicate)
- SQLite persistence and local asset storage with rollback cleanup

## Next steps

1. **Extraction** — add local garment detection and segmentation; store crops
   and masks linked to the source photo.
2. **Minimal garment records** — persist garment id, source photo, asset keys,
   and extraction confidence. No metadata taxonomy yet.
3. **Smoke test** — import one representative selfie and verify extracted
   garment assets on disk and in SQLite.

## Definition of done

- One selfie can be imported without duplicates.
- Garments are extracted and persisted as local assets with stable ids.
- Failed imports and failed extractions leave no orphaned files or rows.
- Tests cover ingestion idempotency, validation failures, and rollback.
