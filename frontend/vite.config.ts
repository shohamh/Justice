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
  build: {
    rolldownOptions: {
      output: {
        // Heavy libraries get their own named chunks. They are only reachable
        // through lazy routes / lazy modals, so none of them lands in the entry.
        codeSplitting: {
          groups: [
            // Vite's dynamic-import preload helper would otherwise be hosted inside
            // whichever heavy group chunk loads first (making the entry import it).
            { name: "preload-helper", test: /vite[\\/]preload-helper/, priority: 40 },
            // Keep React core (and small utils shared across heavy libs) out of the heavy-library chunks so the entry never has to
            // statically download e.g. pdfjs just to get React.
            { name: "react-vendor", test: /node_modules[\\/](react|react-dom|scheduler|clsx|tiny-invariant|warning)[\\/]/, priority: 30 },
            { name: "mermaid", test: /node_modules[\\/]mermaid[\\/]/, priority: 20 },
            { name: "react-pdf", test: /node_modules[\\/](react-pdf|pdfjs-dist)[\\/]/, priority: 20 },
            { name: "recharts", test: /node_modules[\\/](recharts|d3-[^\\/]+|victory-vendor)[\\/]/, priority: 20 },
            { name: "fullcalendar", test: /node_modules[\\/]@fullcalendar[\\/]/, priority: 20 },
            { name: "katex", test: /node_modules[\\/](katex|react-katex)[\\/]/, priority: 20 },
            {
              name: "markdown",
              test: /node_modules[\\/](react-markdown|remark[^\\/]*|rehype[^\\/]*|unified|mdast[^\\/]*|hast[^\\/]*|micromark[^\\/]*|unist[^\\/]*|vfile[^\\/]*)[\\/]/,
              priority: 20,
            },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    allowedHosts: [".trycloudflare.com", ".ts.net"],
    proxy: {
      "/api/file-download/": {
        target: process.env.VITE_FILE_GATEWAY_URL ?? "http://localhost:8080",
        changeOrigin: true,
        xfwd: true,
      },
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
      "/api/file-download/": {
        target: process.env.VITE_FILE_GATEWAY_URL ?? "http://localhost:8080",
        changeOrigin: true,
        xfwd: true,
      },
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
