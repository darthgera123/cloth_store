# Cloth Store — storefront guide

Canonical documentation for the **Cloth Store** editorial catalogue storefront
shipped from this repository. The live app is a read-only static site backed by
pre-computed JSON and image assets — there is **no FastAPI layer**, **no SQLite
database**, and **no `/api/v1` routes** in the current checkout.

## Quick start

```bash
cd /path/to/cloth_store
uv sync --group dev

# Refresh storefront payload (catalogue + styling + outfit/lucky data)
uv run cloth-store-web-build --repo-root .

# Serve locally (stdlib HTTP via cloth-store-web)
uv run cloth-store-web --repo-root .
```

Open **http://127.0.0.1:8080/** (default bind: `127.0.0.1:8080`).

Optional smoke check without keeping the server running:

```bash
uv run cloth-store-web --repo-root . --smoke
```

## Architecture

| Piece | Location / command |
|-------|-------------------|
| Web shell | `src/cloth_store/web/` (`index.html`, `static/app.js`, `static/styles.css`) |
| Storefront payload | `final_catalog/storefront.json` (built by `cloth-store-web-build`) |
| Catalogue images | `final_catalog/**/output.png` (512px derivatives) |
| Styling selfies | `final_selfies/` (refocus crops) with fallback to `data/outfit_*.jpeg` |
| HTTP server | `cloth-store-web` → `src/cloth_store/web_server.py` |

The browser loads `/final_catalog/storefront.json` at runtime (or embedded JSON in
the offline static bundle). All catalogue browsing, styling resolution, outfit
generation, and lucky pairing run client-side against that payload.

## HTTP server and MIME types

`cloth-store-web` is a lightweight stdlib `TCPServer` — not uvicorn/FastAPI.
It serves:

| Path prefix | Files |
|-------------|-------|
| `/` | `src/cloth_store/web/index.html` |
| `/static/` | CSS and JS from `src/cloth_store/web/static/` |
| `/final_catalog/` | Catalogue assets and `storefront.json` |
| `/final_selfies/` | Packaged refocus portrait crops |
| `/data/` | Original mirror-selfie sources (fallback only) |

Static assets use `SimpleHTTPRequestHandler.guess_type()` for `Content-Type`
headers. CSS is served as `text/css`, JavaScript as `text/javascript` (or the
platform equivalent), and HTML as `text/html; charset=utf-8`. Incorrect MIME
types prevent browsers from applying stylesheets or executing scripts even when
HTTP status is 200 — the server must pass the full guessed type string, not a
single character from it.

Customize bind address/port:

```bash
uv run cloth-store-web --repo-root . --host 0.0.0.0 --port 8080
```

## Catalogue and images

- **33 indexed items** (37 logical garments from 59 manifest observations) across
  tops, blazers, dresses, and bottoms from `final_catalog/catalog.json`.
- Four role-level observations are excluded from indexing but remain in the
  packaging bundle; see [Catalog curation](#catalog-curation).
- Cards and detail modals use **512px** `output.png` images only (`/final_catalog/.../output.png`).
- **1K masters** (`output_1k.png`) exist in the pipeline bundle but are not served by the storefront.
- Descriptions are magazine-style copy generated under editorial constraints (see
  [`prompts/catalogue_description_system.md`](../prompts/catalogue_description_system.md)).

## Per-outfit selfie refocus assets

Styling associations, the outfit generator hero, and detail-modal selfie slides
prefer **blur-only refocused portrait crops** from `final_selfies/`. Original
mirror selfies under `data/` are used only when no refocus deliverable exists.

### Layout

```
final_selfies/
  manifest.json
  outfit_N/
    crop_refocused.jpg   # default display variant
    crop_only.jpg        # review / no-blur variant
    metadata.json
```

### Variant selection

The styling resolver (`resolve_fixture_selfie_asset` in `services/styling.py`)
reads each fixture's `metadata.json`:

| Condition | Display file | Example |
|-----------|--------------|---------|
| Normal outfit (`review_required: false`) | `crop_refocused.jpg` | `/final_selfies/outfit_10/crop_refocused.jpg` |
| Review required (`review_required: true`) | `crop_only.jpg` | `/final_selfies/outfit_14/crop_only.jpg` |
| Metadata recommends `crop_only` | `crop_only.jpg` | `/final_selfies/outfit_29/crop_only.jpg` |

Review-required fixtures in the current catalogue include **outfit_14** and
**outfit_29** (subject clipping and low mask coverage respectively). **outfit_30**
was recovered via Qwen full-person bbox + SAM re-segmentation and uses
``crop_refocused.jpg``.

### Fallback when refocus is missing

If `final_selfies/outfit_N/metadata.json` is absent, unreadable, or the preferred
variant file is missing, the resolver falls back to the original source mirror
selfie:

```
/data/outfit_N.jpeg
```

If no source selfie exists either, the association reports `selfie.available: false`
and UI surfaces omit the selfie slide.

### Live vs static bundle URLs

| Mode | Selfie URL pattern |
|------|-------------------|
| Live (`cloth-store-web`) | `/final_selfies/outfit_N/crop_refocused.jpg` or `.../crop_only.jpg` |
| Static bundle (`dist/lavani-closet/`) | `assets/selfies/outfit_N/crop_refocused.jpg` or `.../crop_only.jpg` |

Regenerate refocus deliverables: see [`final_selfies/README.md`](../final_selfies/README.md)
and [`bench/selfie_refocus/README.md`](../bench/selfie_refocus/README.md).

## Storefront experience

### Browse and search

- Sectioned grid: **Tops**, **Blazers**, **Dresses**, **Bottoms**
- Full-text search with debounced client-side filtering
- Category tabs (All / Tops / Blazers / Dresses / Bottoms)

### Item detail modal

Click any catalogue card to open an accessible portrait-oriented modal:

- Carousel of catalogue `output.png` views
- **Fashion Advice** caption pairing the item with its documented partner(s)
- Styling selfie slide when a refocus (or fallback) asset is available

### Generate an Outfit

Picks a random **same-fixture top/bottom pair** that has a documented mirror-selfie
association. Shows the refocused selfie as the hero image plus both garment cards.
Uses a deterministic seed per session for reproducible "Regenerate" behavior.
**Dresses are excluded** — only separates with fixture selfies qualify.

### I'm Feeling Lucky

Picks a random **catalogue-only look** that has **not** been photographed together on
any documented fixture selfie. Supported look types:

| Look type | Pieces |
|-----------|--------|
| Top + Bottom | non-blazer top, bottom |
| Blazer + Top + Bottom | blazer, non-blazer top, bottom |
| Blazer + Dress | blazer, dress |

Shows catalogue images only — no reference selfie hero. Selection balances across
look types when regenerating. Useful for exploring pairings outside the mirror-selfie
corpus.

This is distinct from **Generate an Outfit**, which requires a same-fixture selfie
and always returns a documented top/bottom pair.

## Catalog curation

The storefront reflects **user-confirmed curation**, not raw VLM output:

- **Identity deduplication** — manual groups in
  `bench/catalog_generation/garment_identities.json` merge duplicate physical
  garments to one canonical catalog card per group (e.g. tan straight-fit
  trousers from outfits 1, 2, 7, 8, 9 → `outfit_2/bottom`; khaki straight-fit
  trousers from outfits 23–25 → `outfit_24/bottom`, kept distinct from tan).
- **Role-level exclusions** — four observations are omitted from indexing while
  retained counterparts and fixture selfies stay usable:
  `outfit_31/bottom`, `outfit_27/dress`, `outfit_19/top`, `outfit_2/top`.
- **Blazers section** — `outfit_3/top` and `outfit_4/top` appear under Blazers
  in the UI but remain `role=top` for pairing; `outfit_19/top` is excluded.

Curation-only changes rebuild derived JSON deterministically — no model/API calls.
See [`bench/catalog_generation/GARMENT_IDENTITIES.md`](../bench/catalog_generation/GARMENT_IDENTITIES.md)
for the full identity table, expected counts, and rebuild commands.

## Limitations

- **Read-only** — no cart, checkout, accounts, or inventory mutations.
- **Static data** — reflects `storefront.json` at build time; restart or rebuild
  after catalogue/refocus changes.
- **Lexical search only** — no embedding or semantic retrieval in the storefront.
- **Outfit generator scope** — separates with available fixture selfies only; dresses
  and items without partners are skipped.
- **Lucky looks** — catalogue views only (top+bottom, blazer+top+bottom, blazer+dress);
  no composite or generative try-on imagery; no selfie hero.
- **Selfie coverage** — refocus crops exist for packaged fixtures; fallback originals
  may differ in framing from catalogue renders.
- **Offline bundle** — see [`static-bundle-guide.md`](static-bundle-guide.md); uses
  embedded JSON, relative asset paths (`assets/catalogue/`, `assets/selfies/`), and
  Windows launchers (`start-lavani.bat`, `start-lavani.ps1`) in `dist/lavani-closet/`.

## Related docs

- [`README.md`](../README.md) — repository entry point
- [`static-bundle-guide.md`](static-bundle-guide.md) — shareable `dist/lavani-closet.zip`
- [`final_catalog/README.md`](../final_catalog/README.md) — catalogue packaging
- [`bench/catalog_generation/GARMENT_IDENTITIES.md`](../bench/catalog_generation/GARMENT_IDENTITIES.md) — identity/exclusion curation
- [`RECONSTRUCTION_PIPELINE.md`](../RECONSTRUCTION_PIPELINE.md) — generation pipeline

## Verification

Storefront contract is covered by `test_website_static_catalog_contract` in
`tests/test_scenarios.py` (catalogue counts, refocus URL resolution, web server
smoke fetch).

```bash
uv sync --group dev
uv run pytest tests/test_scenarios.py::test_website_static_catalog_contract -q
```
