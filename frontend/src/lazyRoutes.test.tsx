// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");

describe("App routes", () => {
  it("loads pages lazily; only the login and change-password pages stay eager", () => {
    const staticPageImports = app.match(/^import .* from "\.\/pages\/.*";$/gm) ?? [];
    expect(staticPageImports.sort()).toEqual([
      'import ChangePasswordPage from "./pages/ChangePasswordPage";',
      'import LoginPage from "./pages/LoginPage";',
    ]);
    expect(app).toContain("lazy(() => import(");
    expect(app).toContain("<Suspense");
  });
});

