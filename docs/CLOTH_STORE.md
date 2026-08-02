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
| Styling selfies | `final_selfies/` (neck-down privacy crops) with refocus/original fallbacks |
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

## Per-outfit selfie assets

Styling associations, the outfit generator hero, and detail-modal selfie slides
prefer **neck-down privacy crops** from `final_selfies/`. Refocused portrait crops
and original mirror selfies under `data/` are used only when no valid neck-down
deliverable exists.

### Layout

```
final_selfies/
  manifest.json
  outfit_N/
    crop_neck_down.jpg   # default display variant (privacy)
    crop_refocused.jpg   # refocus fallback
    crop_only.jpg        # review / no-blur fallback
    metadata.json
```

### Variant selection

The styling resolver (`resolve_fixture_selfie_asset` in `services/styling.py`)
reads each fixture's `metadata.json` in this order:

| Priority | Condition | Display file | Example |
|----------|-----------|--------------|---------|
| 1 | Valid `privacy_variant` (QC `pass` or `user_approved`) | `crop_neck_down.jpg` | `/final_selfies/outfit_10/crop_neck_down.jpg` |
| 2 | Normal outfit (`review_required: false`) | `crop_refocused.jpg` | `/final_selfies/outfit_10/crop_refocused.jpg` |
| 3 | Review required (`review_required: true`) | `crop_only.jpg` | `/final_selfies/outfit_14/crop_only.jpg` |
| 4 | Metadata recommends `crop_only` | `crop_only.jpg` | `/final_selfies/outfit_29/crop_only.jpg` |
| 5 | No refocus deliverable | original source | `/data/outfit_N.jpeg` |

A neck-down variant is **valid** when `privacy_variant.method` is
`neck_down_privacy_v1`, QC status is `pass` or `user_approved`, the file exists on
disk, and SHA-256 matches metadata when present.

All 31 current fixtures have approved neck-down variants. Review-required fixtures
**outfit_14** (user-approved neck-down) and **outfit_29** (original-source neck-down)
still display `crop_neck_down.jpg` when QC passes. **outfit_30** uses neck-down from
its recovered refocus source.

### Privacy intent

Neck-down crops exclude the face/jaw region for public storefront display while
preserving garment styling context. Refocus and original variants remain packaged
for review and compatibility fallback.

### Fallback when neck-down is missing

If `privacy_variant` is absent, QC-failed, or the file/hash is invalid, the resolver
falls back to refocus variants (`crop_refocused` or `crop_only`). If
`final_selfies/outfit_N/metadata.json` is absent, unreadable, or the preferred
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
| Live (`cloth-store-web`) | `/final_selfies/outfit_N/crop_neck_down.jpg` (or refocus/original fallback) |
| Static bundle (`dist/cloth-store/`) | `assets/selfies/outfit_N/crop_neck_down.jpg` only |

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
- Styling selfie slide when a neck-down (or fallback) asset is available

### Generate an Outfit

Picks a random **same-fixture top/bottom pair** that has a documented mirror-selfie
association. Shows the neck-down privacy selfie as the hero image plus both garment cards.
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
look types and uses a bounded recent-history shuffle bag so **Try Another** avoids
immediate exact repeats, consecutive same-type streaks, and reusing the same key
piece (especially blazers) when eligible alternatives exist — while staying random.

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
- **Selfie coverage** — neck-down privacy crops exist for all 31 packaged fixtures;
  refocus/original fallbacks may differ in framing from catalogue renders.
- **Offline bundle** — see [`static-bundle-guide.md`](static-bundle-guide.md); extract
  `dist/cloth-store.zip` and double-click `index.html`. Uses embedded JSON and
  relative asset paths (`assets/catalogue/`, `assets/selfies/`). HTTP serving is
  optional if a browser blocks local file access.

## Related docs

- [`README.md`](../README.md) — repository entry point
- [`static-bundle-guide.md`](static-bundle-guide.md) — shareable `dist/cloth-store.zip`
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
