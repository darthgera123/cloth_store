"""Lightweight stdlib HTTP server for the Lavani's Closet static storefront."""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import threading
import urllib.request
from pathlib import Path

from cloth_store.web import STATIC_ROOT, WEB_ROOT
from cloth_store.web_storefront import (
    DEFAULT_STOREFRONT_JSON,
    build_storefront_bundle,
    write_storefront_bundle,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


def _ensure_storefront(repo_root: Path) -> Path:
    storefront_path = (repo_root / DEFAULT_STOREFRONT_JSON).resolve()
    if not storefront_path.is_file():
        bundle = build_storefront_bundle(repo_root=repo_root)
        write_storefront_bundle(bundle, output_path=storefront_path)
    return storefront_path


class ClothStoreHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serve the static storefront, final_catalog assets, and source selfies."""

    def __init__(
        self,
        *args: object,
        repo_root: Path,
        **kwargs: object,
    ) -> None:
        self._repo_root = repo_root
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: object) -> None:
        if args and isinstance(args[0], str) and args[0].startswith("GET /static/"):
            return
        super().log_message(format, *args)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in {"/", "/index.html"}:
            self._serve_file(WEB_ROOT / "index.html", content_type="text/html; charset=utf-8")
            return

        if path.startswith("/static/"):
            rel = path.removeprefix("/static/")
            self._serve_file(STATIC_ROOT / rel)
            return

        if path.startswith("/final_catalog/"):
            rel = path.removeprefix("/final_catalog/")
            self._serve_file(self._repo_root / "final_catalog" / rel)
            return

        if path.startswith("/data/"):
            rel = path.removeprefix("/data/")
            self._serve_file(self._repo_root / "data" / rel)
            return

        self.send_error(http.HTTPStatus.NOT_FOUND, "Not Found")

    def _serve_file(self, file_path: Path, content_type: str | None = None) -> None:
        resolved = file_path.resolve()
        if not resolved.is_file():
            self.send_error(http.HTTPStatus.NOT_FOUND, "Not Found")
            return

        body = resolved.read_bytes()
        if content_type is None:
            content_type = self.guess_type(str(resolved))[0] or "application/octet-stream"

        self.send_response(http.HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _make_handler(repo_root: Path) -> type[ClothStoreHTTPRequestHandler]:
    return functools.partial(ClothStoreHTTPRequestHandler, repo_root=repo_root)


def run_server(
    *,
    repo_root: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> socketserver.TCPServer:
    _ensure_storefront(repo_root)
    handler = _make_handler(repo_root.resolve())
    server = socketserver.TCPServer((host, port), handler)
    server.allow_reuse_address = True
    return server


def smoke_fetch(
    base_url: str, path: str, *, retries: int = 20, delay: float = 0.05
) -> tuple[int, bytes]:
    import time

    url = f"{base_url.rstrip('/')}{path}"
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.status, response.read()
        except Exception as error:  # noqa: BLE001 - retry transient startup races
            last_error = error
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve Lavani's Closet static storefront (stdlib HTTP, no FastAPI/SQLite).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory)",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Start briefly, fetch / and /final_catalog/storefront.json, then exit",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    server = run_server(repo_root=repo_root, host=args.host, port=args.port)

    if args.smoke:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://{args.host}:{args.port}"
        try:
            status, body = smoke_fetch(base, "/")
            assert status == 200
            assert b"Lavani's Closet" in body
            status, body = smoke_fetch(base, "/final_catalog/storefront.json")
            assert status == 200
            assert b'"items"' in body
        finally:
            server.shutdown()
            server.server_close()
        print("Smoke OK")
        return 0

    print(f"Serving Lavani's Closet at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
