import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
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
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // Playwright specs live in tests/e2e and must not be collected by vitest.
    exclude: ["**/node_modules/**", "**/dist/**", "tests/e2e/**"],
    passWithNoTests: true,
    pool: "threads",
    maxWorkers: 8,
    // Vitest 4 replaces environmentMatchGlobs with projects. Keep pure tests
    // on Node while the remaining component tests use jsdom.
    projects: [
      {
        extends: true,
        test: {
          name: "jsdom",
          environment: "jsdom",
          exclude: [
            "**/node_modules/**",
            "**/dist/**",
            "tests/e2e/**",
            "**/src/api/**/*.test.ts",
            "**/src/utils/**/*.test.ts",
            "**/src/auth/permissions.test.ts",
            "**/src/searchRegistry.test.ts",
            "**/src/i18n/he.test.ts",
          ],
        },
      },
      {
        extends: true,
        test: {
          name: "node",
          environment: "node",
          include: [
            "**/src/api/**/*.test.ts",
            "**/src/utils/**/*.test.ts",
            "**/src/auth/permissions.test.ts",
            "**/src/searchRegistry.test.ts",
            "**/src/i18n/he.test.ts",
          ],
        },
      },
    ],
  },
});
