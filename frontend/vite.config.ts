import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: { port: 5173, host: "0.0.0.0" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    // Playwright specs live in tests/e2e and must not be collected by vitest.
    exclude: ["**/node_modules/**", "**/dist/**", "tests/e2e/**"],
    passWithNoTests: true,
  } as unknown as Record<string, unknown>,
});
