"""Build a shareable static-site bundle for Cloth Store."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cloth_store.web import STATIC_ROOT, WEB_ROOT
from cloth_store.web_storefront import build_storefront_bundle, write_storefront_bundle

BUNDLE_NAME = "lavani-closet"
BUNDLE_VERSION = "1"
CATALOGUE_PREFIX = "assets/catalogue"
SELFIE_PREFIX = "assets/selfies"
DEFAULT_OUTPUT_DIR = Path("dist/lavani-closet")
DEFAULT_ZIP_PATH = Path("dist/lavani-closet.zip")
LAUNCHER_DIR = Path(__file__).resolve().parent / "bundle_launchers"
LAUNCHER_FILES = ("start-lavani.bat", "start-lavani.ps1")

FORBIDDEN_BUNDLE_PARTS = (
    "output_1k.png",
    ".venv",
    ".env",
    ".sqlite",
    ".db",
    "node_modules",
)

PROMPT_SOURCE = Path("prompts/catalogue_description_system.md")
STATIC_BUNDLE_GUIDE_SOURCE = Path("docs/static-bundle-guide.md")
CLOTH_STORE_DOC_SOURCE = Path("docs/CLOTH_STORE.md")

README_TEMPLATE = """# Lavani's Closet — Static Snapshot

This folder is a **standalone static snapshot** of Lavani's Closet.
It does not require the Cloth Store repository, FastAPI, uv, bash, or any
ML/runtime dependencies.

## Contents

| Path | Purpose |
|------|---------|
| `index.html` | Storefront shell (embedded catalogue data for offline use) |
| `static/` | CSS and JavaScript |
| `data/storefront.json` | Pre-computed catalogue, styling, outfit, and lucky-look data |
| `assets/catalogue/` | 512px catalogue `output.png` images referenced by the snapshot |
| `assets/selfies/` | Refocused crops per `outfit_N/` (`crop_refocused.jpg` or `crop_only.jpg`) |
| `docs/` | Storefront and description-prompt documentation |
| `start-lavani.bat` | Windows double-click launcher (Python stdlib HTTP server) |
| `start-lavani.ps1` | Windows PowerShell launcher |
| `manifest.json` | Build metadata and packaged asset inventory |

## Run locally

### Windows

1. Install [Python 3](https://www.python.org/downloads/) if needed. During setup,
   check **Add python.exe to PATH**.
2. Unzip the bundle to any folder (for example `Downloads\\lavani-closet`).
3. Double-click **`start-lavani.bat`**, or right-click **`start-lavani.ps1`** →
   **Run with PowerShell**.
4. Your browser opens **http://127.0.0.1:8080/** automatically.
5. To stop the server, close the console window or press **Ctrl+C** in it.

No FastAPI, uv, bash, or repository checkout is required on Windows.

### macOS / Linux

From this directory:

```bash
python3 -m http.server 8080 --bind 127.0.0.1
```

Then open **http://127.0.0.1:8080/** in your browser. Press **Ctrl+C** in the
terminal to stop the server.

### Direct file open

`index.html` embeds the catalogue payload so basic browsing works when opened
via `file://`. For the most reliable experience (images and modals), use the
local HTTP server above.

## Supported features (offline)

- Browse tops, blazers, dresses, and bottoms
- Search and role filters
- Item detail modal with catalogue carousel and styling selfies
- **Generate an Outfit** — same-fixture top/bottom pairs with selfie hero
- **I'm Feeling Lucky** — catalogue-only looks (top+bottom, blazer+top+bottom, blazer+dress)

## Image policy

- Catalogue cards and modals use **512px** `output.png` derivatives only.
- Selfies prefer blur-only refocused portrait crops from `final_selfies/`:
  - normal outfits → `assets/selfies/outfit_N/crop_refocused.jpg`
  - review-required outfits → `assets/selfies/outfit_N/crop_only.jpg`
  - no refocus deliverable → original `assets/selfies/outfit_N.jpeg`
- No 1K masters, pipeline inputs, or private database files are included.

## Snapshot notice

Data and images reflect the catalogue at build time. Rebuild from the repository
with `uv run cloth-store-static-bundle --repo-root /path/to/cloth_store` to
refresh.
"""


def _json_for_html_embed(data: dict[str, Any]) -> str:
    """Serialize JSON safely for embedding inside a ``<script>`` tag."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def collect_bundle_image_urls(bundle: dict[str, Any]) -> set[str]:
    """Return every catalogue/selfie URL referenced by the storefront payload."""
    urls: set[str] = set()

    for item in bundle.get("items", []):
        if url := item.get("image_url"):
            urls.add(str(url))

    for styling in bundle.get("styling", {}).values():
        for association in styling.get("associations", []):
            selfie = association.get("selfie") or {}
            if url := selfie.get("image_url"):
                urls.add(str(url))

    for candidate in bundle.get("outfit_candidates", []):
        for key in ("top", "bottom"):
            garment = candidate.get(key) or {}
            if url := garment.get("image_url"):
                urls.add(str(url))
        selfie = candidate.get("selfie") or {}
        if url := selfie.get("image_url"):
            urls.add(str(url))

    for look in bundle.get("lucky_look_candidates", []):
        for piece in look.get("pieces", []):
            if url := piece.get("image_url"):
                urls.add(str(url))

    return urls


def _catalogue_source_path(repo_root: Path, bundle_url: str) -> Path:
    rel = bundle_url.removeprefix(f"{CATALOGUE_PREFIX}/")
    return repo_root / "final_catalog" / rel


def _selfie_source_path(repo_root: Path, bundle_url: str) -> Path:
    rel = bundle_url.removeprefix(f"{SELFIE_PREFIX}/")
    refocus_path = repo_root / "final_selfies" / rel
    if refocus_path.is_file():
        return refocus_path
    return repo_root / "data" / rel


def _copy_asset(source: Path, destination: Path, *, manifest_root: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {
        "path": destination.relative_to(manifest_root).as_posix(),
        "sha256": digest,
        "size_bytes": destination.stat().st_size,
    }


def prepare_bundle_index_html(source_html: str, bundle: dict[str, Any]) -> str:
    """Rewrite web shell paths and embed storefront JSON for static/file use."""
    html = source_html.replace('href="/static/', 'href="static/')
    html = html.replace('src="/static/', 'src="static/')
    html = html.replace(
        '<html lang="en">',
        '<html lang="en" data-storefront-url="data/storefront.json">',
    )
    embedded = _json_for_html_embed(bundle)
    embed_tag = f'    <script type="application/json" id="storefront-data">{embedded}</script>\n'
    html = html.replace(
        '    <script src="static/app.js" defer></script>',
        embed_tag + '    <script src="static/app.js" defer></script>',
    )
    return html


def _prepare_bundle_storefront_doc(source_text: str) -> str:
    """Rewrite repo-root links for the self-contained bundle docs tree."""
    text = source_text.replace(
        "../prompts/catalogue_description_system.md",
        "catalogue_description_system.md",
    )
    # Drop repo-only relative links (targets not shipped in the bundle).
    return re.sub(
        r"\[([^\]]+)\]\(\.\./(?:final_selfies|bench/selfie_refocus|final_catalog|RECONSTRUCTION_PIPELINE)[^)]*\)",
        r"\1 (repository only)",
        text,
    )


def _write_bundle_launchers(output_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name in LAUNCHER_FILES:
        source = LAUNCHER_DIR / name
        if not source.is_file():
            raise FileNotFoundError(f"Missing bundle launcher template: {source}")
        dest = output_dir / name
        shutil.copy2(source, dest)
        entries.append(
            {
                "path": dest.relative_to(output_dir).as_posix(),
                "source": source.as_posix(),
                "size_bytes": dest.stat().st_size,
            }
        )
    return entries


def _write_bundle_docs(output_dir: Path, repo_root: Path) -> list[dict[str, Any]]:
    docs_dir = output_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []

    guide_source = repo_root / STATIC_BUNDLE_GUIDE_SOURCE
    if guide_source.is_file():
        dest = docs_dir / "static-bundle-guide.md"
        shutil.copy2(guide_source, dest)
        entries.append(
            {"path": dest.relative_to(output_dir).as_posix(), "source": guide_source.as_posix()}
        )

    storefront_doc_source = repo_root / CLOTH_STORE_DOC_SOURCE
    if storefront_doc_source.is_file():
        dest = docs_dir / "CLOTH_STORE.md"
        dest.write_text(
            _prepare_bundle_storefront_doc(storefront_doc_source.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        entries.append(
            {
                "path": dest.relative_to(output_dir).as_posix(),
                "source": storefront_doc_source.as_posix(),
            }
        )

    prompt_source = repo_root / PROMPT_SOURCE
    if prompt_source.is_file():
        dest = docs_dir / "catalogue_description_system.md"
        shutil.copy2(prompt_source, dest)
        entries.append(
            {"path": dest.relative_to(output_dir).as_posix(), "source": prompt_source.as_posix()}
        )

    return entries


def build_static_bundle(
    *,
    repo_root: Path,
    output_dir: Path,
    zip_path: Path | None = None,
) -> dict[str, Any]:
    """Build a clean static bundle directory and optional zip archive."""
    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bundle = build_storefront_bundle(
        repo_root=repo_root,
        selfies_url_prefix=SELFIE_PREFIX,
        assets_url_prefix=CATALOGUE_PREFIX,
    )

    data_dir = output_dir / "data"
    storefront_path = data_dir / "storefront.json"
    write_storefront_bundle(bundle, output_path=storefront_path)

    static_dir = output_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    static_entries: list[dict[str, Any]] = []
    for name in ("app.js", "styles.css"):
        source = STATIC_ROOT / name
        dest = static_dir / name
        static_entries.append(_copy_asset(source, dest, manifest_root=output_dir))

    catalogue_entries: list[dict[str, Any]] = []
    selfie_entries: list[dict[str, Any]] = []
    for url in sorted(collect_bundle_image_urls(bundle)):
        if url.startswith(f"{CATALOGUE_PREFIX}/"):
            source = _catalogue_source_path(repo_root, url)
            dest = output_dir / url
            if not source.is_file():
                raise FileNotFoundError(f"Missing catalogue asset for {url}: {source}")
            catalogue_entries.append(_copy_asset(source, dest, manifest_root=output_dir))
        elif url.startswith(f"{SELFIE_PREFIX}/"):
            source = _selfie_source_path(repo_root, url)
            dest = output_dir / url
            if not source.is_file():
                raise FileNotFoundError(f"Missing selfie asset for {url}: {source}")
            selfie_entries.append(_copy_asset(source, dest, manifest_root=output_dir))
        else:
            raise ValueError(f"Unexpected bundle asset URL: {url}")

    index_html = prepare_bundle_index_html(
        (WEB_ROOT / "index.html").read_text(encoding="utf-8"),
        bundle,
    )
    index_path = output_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    (output_dir / "README.md").write_text(README_TEMPLATE, encoding="utf-8")
    launcher_entries = _write_bundle_launchers(output_dir)
    doc_entries = _write_bundle_docs(output_dir, repo_root)

    build_timestamp = datetime.now(tz=UTC).isoformat()
    manifest: dict[str, Any] = {
        "bundle_name": BUNDLE_NAME,
        "bundle_version": BUNDLE_VERSION,
        "build_timestamp": build_timestamp,
        "repo_root": str(repo_root),
        "total_items": bundle.get("total_items", 0),
        "outfit_candidates": len(bundle.get("outfit_candidates", [])),
        "lucky_look_candidates": len(bundle.get("lucky_look_candidates", [])),
        "lucky_look_candidate_counts": bundle.get("lucky_look_candidate_counts", {}),
        "data_files": [
            {
                "path": storefront_path.relative_to(output_dir).as_posix(),
                "sha256": hashlib.sha256(storefront_path.read_bytes()).hexdigest(),
                "size_bytes": storefront_path.stat().st_size,
            }
        ],
        "static_files": static_entries,
        "catalogue_images": catalogue_entries,
        "selfie_images": selfie_entries,
        "docs": doc_entries,
        "launchers": launcher_entries,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    zip_info: dict[str, Any] | None = None
    if zip_path is not None:
        zip_path = zip_path.resolve()
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(output_dir.parent).as_posix())
        zip_info = {
            "path": str(zip_path),
            "size_bytes": zip_path.stat().st_size,
            "file_count": len(list(output_dir.rglob("*"))),
        }

    return {
        "output_dir": str(output_dir),
        "zip": zip_info,
        "manifest": manifest,
        "bundle": bundle,
    }


def _iter_bundle_files(bundle_dir: Path) -> list[Path]:
    return [path for path in bundle_dir.rglob("*") if path.is_file()]


def _assert_no_forbidden_paths(files: list[Path]) -> None:
    for path in files:
        rel = path.as_posix()
        for forbidden in FORBIDDEN_BUNDLE_PARTS:
            if forbidden in rel:
                raise AssertionError(f"Forbidden bundle path matched {forbidden!r}: {rel}")


def _collect_html_asset_refs(index_html: str) -> set[str]:
    refs: set[str] = set()
    for match in re.finditer(r'(?:href|src)="([^"]+)"', index_html):
        refs.add(match.group(1))
    return refs


def _validate_bundle_launchers(bundle_dir: Path) -> None:
    required_markers = (
        "127.0.0.1:8080",
        "http.server",
        "8080",
        "127.0.0.1",
    )
    forbidden_patterns = (
        "/users/",
        "/home/",
        "/path/to/",
        "cloth_store",
        "dist/lavani-closet",
    )
    for name in LAUNCHER_FILES:
        launcher_path = bundle_dir / name
        if not launcher_path.is_file():
            raise AssertionError(f"Missing launcher: {name}")
        text = launcher_path.read_text(encoding="utf-8")
        for marker in required_markers:
            if marker not in text:
                raise AssertionError(f"Launcher {name} missing expected marker: {marker!r}")
        lowered = text.lower()
        if "py" not in lowered and "python" not in lowered:
            raise AssertionError(f"Launcher {name} must reference py or python")
        for forbidden in forbidden_patterns:
            if forbidden in text:
                raise AssertionError(f"Launcher {name} contains hardcoded path: {forbidden!r}")
    bat_text = (bundle_dir / "start-lavani.bat").read_text(encoding="utf-8")
    assert "%~dp0" in bat_text or 'cd /d "%~dp0"' in bat_text
    ps1_text = (bundle_dir / "start-lavani.ps1").read_text(encoding="utf-8")
    assert "$PSScriptRoot" in ps1_text


def _validate_featured_bundle_assets(bundle_dir: Path, bundle: dict[str, Any]) -> None:
    dress_ids = {
        item["catalog_id"] for item in bundle.get("items", []) if item.get("role") == "dress"
    }
    assert "outfit_30_dress" in dress_ids, "outfit_30_dress must be in the bundle payload"

    outfit_30_catalogue = bundle_dir / "assets/catalogue/outfit_30/dress/output.png"
    if not outfit_30_catalogue.is_file():
        raise AssertionError("Missing outfit_30 catalogue image")

    outfit_30_refocus = bundle_dir / "assets/selfies/outfit_30/crop_refocused.jpg"
    if not outfit_30_refocus.is_file():
        raise AssertionError("Missing outfit_30 refocus selfie asset")

    outfit_10_refocus = bundle_dir / "assets/selfies/outfit_10/crop_refocused.jpg"
    outfit_14_crop_only = bundle_dir / "assets/selfies/outfit_14/crop_only.jpg"
    if not outfit_10_refocus.is_file():
        raise AssertionError("Missing outfit_10 crop_refocused.jpg")
    if not outfit_14_crop_only.is_file():
        raise AssertionError("Missing outfit_14 crop_only.jpg (review-required variant)")


def _http_smoke(base_url: str, path: str) -> tuple[int, bytes]:
    url = f"{base_url.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read()


def validate_static_bundle(bundle_dir: Path, *, run_http_smoke: bool = True) -> dict[str, Any]:
    """Validate bundle layout, references, and optional HTTP serving."""
    bundle_dir = bundle_dir.resolve()
    files = _iter_bundle_files(bundle_dir)
    _assert_no_forbidden_paths(files)

    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file():
        raise AssertionError("manifest.json is missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    storefront_path = bundle_dir / "data" / "storefront.json"
    if not storefront_path.is_file():
        raise AssertionError("data/storefront.json is missing")

    bundle = json.loads(storefront_path.read_text(encoding="utf-8"))
    assert int(bundle.get("total_items", 0)) > 0
    assert bundle.get("outfit_candidates")
    assert bundle.get("lucky_look_candidates")

    _validate_bundle_launchers(bundle_dir)
    _validate_featured_bundle_assets(bundle_dir, bundle)

    for url in collect_bundle_image_urls(bundle):
        asset_path = bundle_dir / url
        if not asset_path.is_file():
            raise AssertionError(f"Missing referenced asset: {url}")
        if "output_1k" in url:
            raise AssertionError(f"1K asset must not be bundled: {url}")

    index_html = (bundle_dir / "index.html").read_text(encoding="utf-8")
    assert 'id="storefront-data"' in index_html
    assert 'data-storefront-url="data/storefront.json"' in index_html

    for ref in _collect_html_asset_refs(index_html):
        if ref.startswith(("http://", "https://", "//", "data:", "#")):
            continue
        if ref.startswith("/"):
            raise AssertionError(f"Absolute local reference not allowed in bundle HTML: {ref}")
        resolved = bundle_dir / ref
        if not resolved.is_file() and not (bundle_dir / ref.split("?", 1)[0]).is_file():
            raise AssertionError(f"HTML reference does not resolve: {ref}")

    app_js = (bundle_dir / "static/app.js").read_text(encoding="utf-8")
    assert "storefront-data" in app_js
    assert "/api/v1" not in app_js
    assert "Gathering the latest edit from the catalogue." in app_js

    smoke: dict[str, Any] | None = None
    if run_http_smoke:
        import functools
        import http.server
        import socket
        import socketserver
        import threading
        import time

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler,
            directory=str(bundle_dir),
        )
        server = socketserver.TCPServer(("127.0.0.1", port), handler)
        server.allow_reuse_address = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        base = f"http://127.0.0.1:{port}"
        try:
            brand_match = re.search(
                r'<h1 class="brand-title">([^<]+)</h1>',
                index_html,
            )
            assert brand_match is not None
            status, body = _http_smoke(base, "/")
            assert status == 200
            assert brand_match.group(1).encode() in body
            status, body = _http_smoke(base, "/data/storefront.json")
            assert status == 200
            assert b'"outfit_candidates"' in body
            sample_url = bundle["items"][0]["image_url"]
            status, body = _http_smoke(base, f"/{sample_url}")
            assert status == 200
            smoke = {"status": "ok", "port": port, "sample_image": sample_url}
        finally:
            server.shutdown()
            server.server_close()

    return {
        "file_count": len(files),
        "total_items": bundle["total_items"],
        "outfit_candidates": len(bundle["outfit_candidates"]),
        "lucky_look_candidates": len(bundle["lucky_look_candidates"]),
        "lucky_look_candidate_counts": bundle.get("lucky_look_candidate_counts", {}),
        "manifest": manifest,
        "http_smoke": smoke,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a shareable static Cloth Store bundle (directory + zip).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Bundle output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--zip",
        type=Path,
        default=DEFAULT_ZIP_PATH,
        help=f"Zip archive path (default: {DEFAULT_ZIP_PATH})",
    )
    parser.add_argument(
        "--skip-zip",
        action="store_true",
        help="Do not create the zip archive",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run bundle validation after build",
    )
    parser.add_argument(
        "--validate-only",
        type=Path,
        metavar="BUNDLE_DIR",
        help="Validate an existing bundle directory and exit",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()

    if args.validate_only is not None:
        report = validate_static_bundle(args.validate_only.resolve())
        print(json.dumps(report, indent=2))
        return 0

    result = build_static_bundle(
        repo_root=repo_root,
        output_dir=args.output_dir
        if args.output_dir.is_absolute()
        else repo_root / args.output_dir,
        zip_path=None
        if args.skip_zip
        else (args.zip if args.zip.is_absolute() else repo_root / args.zip),
    )

    file_count = len(list(Path(result["output_dir"]).rglob("*")))
    print(f"Wrote {result['output_dir']} ({file_count} paths)")
    if result["zip"] is not None:
        print(
            f"Wrote {result['zip']['path']} "
            f"({result['zip']['size_bytes']:,} bytes, {result['zip']['file_count']} files)"
        )

    if args.validate:
        report = validate_static_bundle(Path(result["output_dir"]))
        print("Validation OK:")
        print(json.dumps(report, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
