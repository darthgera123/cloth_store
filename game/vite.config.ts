import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// GitHub Pages serves the app from a subpath; set BASE_PATH at build time.
export default defineConfig({
  base: process.env.BASE_PATH ?? "/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve("index.html"),
        host: resolve("host/index.html"),
        display: resolve("display/index.html"),
        join: resolve("join/index.html"),
      },
    },
  },
  server: { port: 5173 },
});
