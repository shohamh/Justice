import { test as base, type Page } from "@playwright/test";

import { loginAs, type Role } from "./auth";

type SharedFixtures = {
  loginAsRole: (role: Role) => Promise<Page>;
};

export const test = base.extend<SharedFixtures>({
  page: async ({ page }, use) => {
    await page.goto("/");
    await use(page);
  },
  loginAsRole: async ({ page }, use) => {
    await use((role) => loginAs(page, role));
  },
});

export { expect } from "@playwright/test";
