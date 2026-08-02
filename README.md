# My GFs Closet — Static Snapshot

This folder is a **standalone static snapshot** of My GFs Closet.
It does not require the Cloth Store repository, FastAPI, uv, Python, bash, or
any ML/runtime dependencies.

## Open the storefront

1. Extract **`cloth-store.zip`** to any folder (for example `Downloads/cloth-store`).
2. Double-click **`index.html`**.

The site loads from your browser using relative CSS, JavaScript, and images.
Catalogue data is embedded in the page, so no server, fetch, or network setup
is required for the primary experience.

**Important:** Do not open `index.html` from inside the zip without extracting
first — relative paths need the full folder layout (`static/`, `assets/`, etc.).

## Contents

| Path | Purpose |
|------|---------|
| `index.html` | Storefront shell (embedded catalogue data for offline use) |
| `static/` | CSS and JavaScript |
| `data/storefront.json` | Pre-computed catalogue, styling, outfit, and lucky-look data |
| `assets/catalogue/` | 512px catalogue `output.png` images referenced by the snapshot |
| `assets/selfies/` | Neck-down privacy crops per `outfit_N/` (`crop_neck_down.jpg`) |
| `docs/` | Storefront and description-prompt documentation |
| `manifest.json` | Build metadata and packaged asset inventory |

## Optional: serve over HTTP

If a browser blocks local file access or you prefer a URL, serve this folder
with any static HTTP server. Python's stdlib server is enough:

```bash
python3 -m http.server 8080 --bind 127.0.0.1
```

Then open **http://127.0.0.1:8080/**. Press **Ctrl+C** in the terminal to stop.
No FastAPI, uv, or repository checkout is required.

| | Double-click `index.html` | HTTP server (optional) |
|-|---------------------------|------------------------|
| CSS / JS | Relative `static/...` paths | Same |
| Catalogue data | Embedded in `index.html` | Embedded + `data/storefront.json` |
| Images | Relative `assets/...` paths | Same |
| Google Fonts | Optional network fetch | Same |

## Supported features (offline)

- Browse tops, blazers, dresses, and bottoms
- Search and role filters
- Item detail modal with catalogue carousel and styling selfies
- **Generate an Outfit** — same-fixture top/bottom pairs with selfie hero
- **I'm Feeling Lucky** — catalogue-only looks (top+bottom, blazer+top+bottom, blazer+dress)

## Image policy

- Catalogue cards and modals use **512px** `output.png` derivatives only.
- Selfies use QC-approved neck-down privacy crops only:
  - `assets/selfies/outfit_N/crop_neck_down.jpg`
- No refocus crops, original mirror selfies, or face-containing variants are included.
- No 1K masters, pipeline inputs, or private database files are included.

## Snapshot notice

Data and images reflect the catalogue at build time. Rebuild from the repository
with `uv run cloth-store-static-bundle --repo-root /path/to/cloth_store` to
refresh.

The canonical shareable artifact is **`dist/cloth-store.zip`** (this folder).
