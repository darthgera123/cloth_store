/* Local preview server for the built app. Sends no-store for HTML so a
   rebuild is visible immediately; hashed assets are cached hard. */

import path from "node:path";

const root = path.join(import.meta.dir, "dist");
const port = Number(process.env.PORT ?? 8091);

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".woff2": "font/woff2",
  ".ico": "image/x-icon",
};

const server = Bun.serve({
  port,
  fetch(req) {
    const url = new URL(req.url);
    let pathname = decodeURIComponent(url.pathname);
    if (pathname.endsWith("/")) pathname += "index.html";

    const resolved = path.resolve(root, `.${pathname}`);
    if (!resolved.startsWith(root)) return new Response("forbidden", { status: 403 });

    const file = Bun.file(resolved);
    if (file.size > 0) {
      const type = MIME[path.extname(resolved)] ?? "application/octet-stream";
      return new Response(file, {
        headers: {
          "content-type": type,
          "cache-control": type.startsWith("text/html") ? "no-store" : "public, max-age=31536000",
        },
      });
    }

    const fallback = Bun.file(path.join(root, "index.html"));
    if (fallback.size > 0) {
      return new Response(fallback, {
        headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
      });
    }
    return new Response("Build the client first: bun run build", { status: 503 });
  },
});

console.log(`Game Night on http://127.0.0.1:${server.port}/`);
