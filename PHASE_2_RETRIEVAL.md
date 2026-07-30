# Phase 2: Retrieval and Collections

## Objective

Retrieve relevant garments and assemble useful collections or outfits from
natural-language requests.

## Query pipeline

```text
user query
  -> classify intent
  -> extract structured constraints
  -> filter eligible garments
  -> retrieve semantic candidates
  -> rerank
  -> build a collection or outfit
  -> return results with explanations
```

## Retrieval modes

- Attribute search, such as "black formal trousers"
- Semantic search, such as "quiet luxury pieces"
- Similarity search from an existing garment
- Dynamic collections, such as "summer workwear"
- Complete outfits, such as "a classy dinner outfit"
- Multi-day plans, such as "work outfits for this week"

## Components

### Query interpretation

Extract intent, garment categories, colours, occasion, formality, season,
weather, exclusions, required garments, and date range into a typed query model.

### Hybrid retrieval

Combine:

- Structured PostgreSQL filters
- Text and image vector similarity
- Lexical matching
- Availability and lifecycle filters
- User preference signals

### Reranking

Balance semantic relevance, metadata confidence, wardrobe preferences, recency,
and result diversity. Every score should expose enough detail to diagnose poor
results.

### Collection builder

Support saved manual collections and reproducible dynamic collections. Store the
source query and retrieval version for generated collections.

### Outfit engine

Build outfits using explicit garment roles and compatibility constraints:

- Required and optional garment slots
- Colour and pattern compatibility
- Consistent formality and style
- Season and weather suitability
- Variety across multiple days
- Locked garments and user exclusions

Rules should enforce validity before ranking; an AI model may rerank valid
outfits but should not be the sole source of compatibility decisions.

### Feedback

Capture saves, likes, dislikes, swaps, worn status, and rejected combinations.
Keep raw feedback separate from derived preference scores.

## Evaluation

- Curate representative queries with expected relevant garments.
- Measure retrieval precision and ranking quality.
- Validate that generated outfits satisfy all hard constraints.
- Track diversity and garment repetition in weekly plans.
- Regression-test every query and model version.

## Definition of done

- All retrieval modes use stable API contracts.
- Structured and semantic constraints work together.
- Collections can be saved, refreshed, and reproduced.
- Outfit generation never returns structurally invalid combinations.
- Weekly plans respect constraints and avoid unnecessary repetition.
- Retrieval quality is measured by a repeatable evaluation suite.
