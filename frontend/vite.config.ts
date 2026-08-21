import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  optimizeDeps: {
    include: ["mermaid"],
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    allowedHosts: [".trycloudflare.com", ".ts.net"],
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_URL ?? "http://localhost:8000",
        changeOrigin: true,
        // Without this, the backend sees every request as coming from the
        // proxy's own loopback connection (127.0.0.1) instead of the real
        // client, collapsing per-IP rate limiting across all users.
        xfwd: true,
      },
    },
  },
  preview: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_URL ?? "http://localhost:8000",
        changeOrigin: true,
        xfwd: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // Playwright specs live in tests/e2e and must not be collected by vitest.
    exclude: ["**/node_modules/**", "**/dist/**", "tests/e2e/**"],
    passWithNoTests: true,
    // Keep the pool single-threaded: several jsdom tests reject Axios-shaped
    // objects that contain functions, and Vitest's worker serializer turns
    // those otherwise-contained failures into cross-worker DataCloneErrors.
    // A single worker keeps failures local and makes the full suite reliable.
    poolOptions: {
      threads: {
        maxThreads: 1,
        minThreads: 1,
      },
    },
  } as unknown as Record<string, unknown>,
});
