# Static bundle guide

The **Cloth Store static bundle** is a portable snapshot of the storefront
that runs without the Cloth Store Python services, ML stack, or repository
checkout.

## Build from the repository

```bash
cd /path/to/cloth_store
uv sync --group dev
uv run cloth-store-static-bundle --repo-root . --validate
```

Outputs:

- `dist/cloth-store/` — unpacked bundle directory
- `dist/cloth-store.zip` — shareable archive

The exporter is idempotent: each run rebuilds a clean output tree from the
current `final_catalog/catalog.json`, styling resolver (refocused selfies from
`final_selfies/` with original-source fallback), and bundled assets.

## Validate an existing bundle

```bash
uv run cloth-store-static-bundle --repo-root . --validate-only dist/cloth-store
```

Or:

```bash
python3 scripts/build_static_bundle.py --repo-root . --validate-only dist/cloth-store
```

Validation checks relative HTML references, embedded JSON, manifest inventory,
forbidden paths (`output_1k`, `.venv`, `.db`, etc.), and runs a brief HTTP smoke
against the bundle root.

## Run the bundle

```bash
cd dist/cloth-store
python3 -m http.server 8080
```

Open **http://127.0.0.1:8080/**.

`index.html` embeds the catalogue payload for basic `file://` browsing, but a
local HTTP server is recommended for reliable image and modal behavior.

## What is included

| Asset | Source in repo | Bundle path |
|-------|----------------|-------------|
| Catalogue 512px images | `final_catalog/**/output.png` | `assets/catalogue/.../output.png` |
| Refocused selfies | `final_selfies/outfit_N/crop_refocused.jpg` or `crop_only.jpg` | `assets/selfies/outfit_N/...` |
| Fallback selfies | `data/outfit_*.jpeg` (only when no refocus file) | `assets/selfies/outfit_*.jpeg` |
| Storefront payload | Built via `build_storefront_bundle()` at export time | `data/storefront.json` (+ embedded in `index.html`) |
| Web shell | `src/cloth_store/web/` | `static/` + `index.html` |
| Docs | `docs/static-bundle-guide.md`, `docs/CLOTH_STORE.md`, prompt reference | `docs/` |

### Selfie variant policy (bundled)

Same rules as the live storefront (see [CLOTH_STORE.md](CLOTH_STORE.md)):

- **Normal outfits** → `assets/selfies/outfit_N/crop_refocused.jpg`
- **Review-required outfits** (e.g. outfit_14, outfit_29) → `assets/selfies/outfit_N/crop_only.jpg`
- **No refocus deliverable** → original `assets/selfies/outfit_N.jpeg` from `data/`

Examples in a fresh build:

```
assets/selfies/outfit_10/crop_refocused.jpg
assets/selfies/outfit_14/crop_only.jpg
```

## What is excluded

- `output_1k.png` and other pipeline inputs
- Virtual environments, SQLite databases, secrets
- Unreferenced catalogue cases or selfies
- ML bench outputs and unrelated source data

## Live vs bundle mode

| | Live (`cloth-store-web`) | Static bundle |
|-|--------------------------|---------------|
| Server | `uv run cloth-store-web --repo-root .` | `python3 -m http.server 8080` in bundle dir |
| Default port | **8080** | **8080** (your choice when serving) |
| Storefront JSON | `/final_catalog/storefront.json` | `data/storefront.json` (also embedded) |
| Catalogue URLs | `/final_catalog/.../output.png` | `assets/catalogue/.../output.png` |
| Selfie URLs | `/final_selfies/outfit_N/...` | `assets/selfies/outfit_N/...` |
| CSS/JS | `/static/...` with correct MIME types via `guess_type()` | `static/...` (stdlib `http.server` defaults) |

Both modes share the same `static/app.js` logic; feature parity includes catalogue
browse/search, detail modal, **Generate an Outfit**, and **I'm Feeling Lucky**.

## Troubleshooting

See `manifest.json` inside the bundle for build timestamp, item counts, and a
full inventory of packaged files with SHA-256 digests.

If images fail to load, confirm you are serving the bundle root (not a parent
directory) and that referenced paths in `data/storefront.json` exist under
`assets/`.

If the **live** repo storefront loads unstyled HTML, verify CSS/JS responses
return `Content-Type: text/css` and `text/javascript` — see
[CLOTH_STORE.md](CLOTH_STORE.md#http-server-and-mime-types).
