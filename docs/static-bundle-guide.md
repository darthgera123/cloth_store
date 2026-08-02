# Static bundle guide

The **Lavani's Closet static bundle** is a portable snapshot of the storefront
that runs without the Cloth Store Python services, ML stack, or repository
checkout. It is a **static website** — HTML, CSS, JavaScript, JSON, and images
only.

## Build from the repository

```bash
cd /path/to/cloth_store
uv sync --group dev
uv run cloth-store-static-bundle --repo-root . --validate
```

Outputs:

- `dist/lavani-closet/` — unpacked bundle directory
- `dist/lavani-closet.zip` — shareable archive

The exporter is idempotent: each run rebuilds a clean output tree from the
current `final_catalog/catalog.json`, styling resolver (refocused selfies from
`final_selfies/` with original-source fallback), bundled assets, and Windows
launchers (`start-lavani.bat`, `start-lavani.ps1`).

## Validate an existing bundle

```bash
uv run cloth-store-static-bundle --repo-root . --validate-only dist/lavani-closet
```

Or:

```bash
python3 scripts/build_static_bundle.py --repo-root . --validate-only dist/lavani-closet
```

Validation checks launcher presence/content, relative HTML references, embedded
JSON, manifest inventory, forbidden paths (`output_1k`, `.venv`, `.db`, etc.),
featured assets (`outfit_30`, refocus selfies), and runs a brief HTTP smoke
against the bundle root.

## Run the bundle

### Windows

1. Install [Python 3](https://www.python.org/downloads/) if needed. During setup,
   check **Add python.exe to PATH**.
2. Unzip `lavani-closet.zip` to any folder.
3. Double-click **`start-lavani.bat`**, or run **`start-lavani.ps1`** in
   PowerShell.
4. Open **http://127.0.0.1:8080/** (the launcher opens it automatically).
5. Stop the server by closing the console window or pressing **Ctrl+C**.

The launchers resolve their own directory, prefer the Windows `py` launcher then
`python`, bind to `127.0.0.1:8080`, and keep the server process visible in the
console. No FastAPI, uv, bash, or repository paths are required.

### macOS / Linux

```bash
cd dist/lavani-closet
python3 -m http.server 8080 --bind 127.0.0.1
```

Open **http://127.0.0.1:8080/**. Press **Ctrl+C** to stop.

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
| Windows launchers | `src/cloth_store/bundle_launchers/` | `start-lavani.bat`, `start-lavani.ps1` |
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
assets/selfies/outfit_30/crop_refocused.jpg
```

## What is excluded

- `output_1k.png` and other pipeline inputs
- Virtual environments, SQLite databases, secrets
- Unreferenced catalogue cases or selfies
- ML bench outputs and unrelated source data

## Live vs bundle mode

| | Live (`cloth-store-web`) | Static bundle |
|-|--------------------------|---------------|
| Server | `uv run cloth-store-web --repo-root .` | Windows: `start-lavani.bat` / `start-lavani.ps1`; macOS/Linux: `python3 -m http.server 8080` |
| Default port | **8080** | **8080** |
| Storefront JSON | `/final_catalog/storefront.json` | `data/storefront.json` (also embedded) |
| Catalogue URLs | `/final_catalog/.../output.png` | `assets/catalogue/.../output.png` |
| Selfie URLs | `/final_selfies/outfit_N/...` | `assets/selfies/outfit_N/...` |
| CSS/JS | `/static/...` with correct MIME types via `guess_type()` | `static/...` (stdlib `http.server` defaults) |

Both modes share the same `static/app.js` logic; feature parity includes catalogue
browse/search, detail modal, **Generate an Outfit**, and **I'm Feeling Lucky**
(catalogue-only looks: top+bottom, blazer+top+bottom, blazer+dress — no selfie hero).

## Troubleshooting

See `manifest.json` inside the bundle for build timestamp, item counts, and a
full inventory of packaged files with SHA-256 digests.

If images fail to load, confirm you are serving the bundle root (not a parent
directory) and that referenced paths in `data/storefront.json` exist under
`assets/`.

On Windows, if the launcher reports Python is missing, reinstall Python 3 and
ensure **Add python.exe to PATH** was checked, then open a new terminal or log
out and back in.

If the **live** repo storefront loads unstyled HTML, verify CSS/JS responses
return `Content-Type: text/css` and `text/javascript` — see
[CLOTH_STORE.md](CLOTH_STORE.md#http-server-and-mime-types).
