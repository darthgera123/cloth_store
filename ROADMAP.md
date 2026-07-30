# Cloth Store Roadmap

## Product goal

Build a private digital wardrobe from mirror selfies: extract garments, enrich
them over time, and eventually retrieve outfits through natural language.

## Delivery phases

### Phase 1: Garment extraction

Import one image at a time, extract garments locally, persist the minimal
output. No metadata enrichment, embeddings, or review workflows yet.

See [PHASE_1_CORPUS.md](PHASE_1_CORPUS.md).

### Phase 2: Retrieval and collections

Add metadata, embeddings, semantic search, collections, and outfit generation.

See [PHASE_2_RETRIEVAL.md](PHASE_2_RETRIEVAL.md).

### Phase 3: Viewer

Build the polished wardrobe catalogue and stylist interface.

See [PHASE_3_VIEWER.md](PHASE_3_VIEWER.md).

## First vertical slice

1. Import one mirror selfie.
2. Extract its garments and persist crops.
3. Confirm assets and records in SQLite and on disk.

This validates the image-processing path before adding metadata, retrieval, or
UI.
