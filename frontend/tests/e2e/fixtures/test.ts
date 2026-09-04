import { test as base, type Page } from "@playwright/test";

import { loginAs, type Role } from "./auth";
import { installDiagnostics } from "../support/diagnostics";

type SharedFixtures = {
  loginAsRole: (role: Role) => Promise<Page>;
};

export const test = base.extend<SharedFixtures>({
  page: async ({ page }, use, testInfo) => {
    installDiagnostics(page, testInfo);
    await page.goto("/");
    await use(page);
  },
  loginAsRole: async ({ page }, use) => {
    await use((role) => loginAs(page, role));
  },
});

export { expect } from "@playwright/test";
