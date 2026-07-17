import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  root: resolve(rootDir, "frontend"),
  base: "./",
  plugins: [react()],
  build: {
    outDir: resolve(rootDir, "dist"),
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:4180",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: [resolve(rootDir, "frontend/src/test/setup.ts")],
  },
});
