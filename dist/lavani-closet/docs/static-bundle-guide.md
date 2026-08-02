# Static bundle guide

The **Lavani's Closet static bundle** is a portable snapshot of the storefront
that runs without the Cloth Store Python services, ML stack, or repository
checkout.

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
current `final_catalog/catalog.json`, styling resolver, and source selfies.

## Validate an existing bundle

```bash
uv run cloth-store-static-bundle --repo-root . --validate-only dist/lavani-closet
```

Or:

```bash
python3 scripts/build_static_bundle.py --repo-root . --validate-only dist/lavani-closet
```

## Run the bundle

```bash
cd dist/lavani-closet
python3 -m http.server 8080
```

Open **http://127.0.0.1:8080/**.

## What is included

| Asset | Source in repo |
|-------|----------------|
| Catalogue 512px images | `final_catalog/**/output.png` referenced by services |
| Selfies | `data/outfit_*.jpeg` referenced by styling resolver |
| Storefront payload | Built via `build_storefront_bundle()` at export time |
| Web shell | `src/cloth_store/web/` with embedded JSON for offline use |

## What is excluded

- `output_1k.png` and other pipeline inputs
- Virtual environments, SQLite databases, secrets
- Unreferenced catalogue cases or selfies
- ML bench outputs and unrelated source data

## Live vs bundle mode

The repository storefront (`uv run cloth-store-web`) continues to serve from
`/final_catalog/storefront.json` with absolute URL prefixes. The bundle rewrites
URLs to relative `assets/catalogue/` and `assets/selfies/` paths and embeds the
payload in `index.html` for `file://` compatibility.

Both modes share the same `static/app.js` logic; live behavior is unchanged.

## Troubleshooting

See `manifest.json` inside the bundle for build timestamp, item counts, and a
full inventory of packaged files with SHA-256 digests.

If images fail to load, confirm you are serving the bundle root (not a parent
directory) and that referenced paths in `data/storefront.json` exist under
`assets/`.
