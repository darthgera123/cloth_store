# Lavani's Closet — Static Snapshot

This folder is a **standalone static snapshot** of the Lavani's Closet storefront.
It does not require the Cloth Store repository, FastAPI, uv, or any ML/runtime
dependencies.

## Contents

| Path | Purpose |
|------|---------|
| `index.html` | Storefront shell (embedded catalogue data for offline use) |
| `static/` | CSS and JavaScript |
| `data/storefront.json` | Pre-computed catalogue, styling, outfit, and lucky-pair data |
| `assets/catalogue/` | 512px catalogue `output.png` images referenced by the snapshot |
| `assets/selfies/` | Source mirror selfies referenced by styling and outfit generator |
| `docs/` | Storefront and description-prompt documentation |
| `manifest.json` | Build metadata and packaged asset inventory |

## Run locally

From this directory:

```bash
python3 -m http.server 8080
```

Then open **http://127.0.0.1:8080/** in your browser.

### Direct file open

`index.html` embeds the catalogue payload so basic browsing works when opened
via `file://`. For the most reliable experience (images and modals), use the
local HTTP server above.

## Supported features (offline)

- Browse tops, dresses, and bottoms
- Search and role filters
- Item detail modal with catalogue carousel and styling selfies
- **Generate an Outfit** — same-fixture top/bottom pairs with selfie hero
- **I'm Feeling Lucky** — cross-fixture top/bottom pairings from catalogue views

## Image policy

- Catalogue cards and modals use **512px** `output.png` derivatives only.
- Selfies are the original source mirror photos bundled for styling context.
- No 1K masters, pipeline inputs, or private database files are included.

## Snapshot notice

Data and images reflect the catalogue at build time. Rebuild from the repository
with `uv run cloth-store-static-bundle --repo-root /path/to/cloth_store` to
refresh.
